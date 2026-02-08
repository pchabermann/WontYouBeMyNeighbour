/*
Copyright 2026.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package controller

import (
	"context"
	"fmt"
	"strings"
	"time"

	corev1 "k8s.io/api/core/v1"
	appsv1 "k8s.io/api/apps/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	"k8s.io/apimachinery/pkg/api/resource"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/intstr"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	logf "sigs.k8s.io/controller-runtime/pkg/log"

	asiv1alpha1 "github.com/anthropics/asi-controller/api/v1alpha1"
)

// AgentTopologyReconciler reconciles a AgentTopology object
type AgentTopologyReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

// +kubebuilder:rbac:groups=asi.asi.anthropic.com,resources=agenttopologies,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=asi.asi.anthropic.com,resources=agenttopologies/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=asi.asi.anthropic.com,resources=agenttopologies/finalizers,verbs=update
// +kubebuilder:rbac:groups="",resources=namespaces,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups="",resources=configmaps,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups="",resources=services,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=apps,resources=statefulsets,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=k8s.cni.cncf.io,resources=network-attachment-definitions,verbs=get;list;watch;create;update;patch;delete

const (
	topologyFinalizer = "asi.anthropic.com/finalizer"
	defaultAgentImage = "localhost:5000/asi-agent:latest"
)

// Reconcile orchestrates the deployment of an ASI agent topology
func (r *AgentTopologyReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := logf.FromContext(ctx)
	log.Info("Reconciling AgentTopology", "name", req.Name, "namespace", req.Namespace)

	// Fetch the AgentTopology instance
	topology := &asiv1alpha1.AgentTopology{}
	if err := r.Get(ctx, req.NamespacedName, topology); err != nil {
		if errors.IsNotFound(err) {
			log.Info("AgentTopology not found, likely deleted")
			return ctrl.Result{}, nil
		}
		log.Error(err, "Failed to get AgentTopology")
		return ctrl.Result{}, err
	}

	// Handle deletion with finalizer
	if !topology.ObjectMeta.DeletionTimestamp.IsZero() {
		if controllerutil.ContainsFinalizer(topology, topologyFinalizer) {
			if err := r.finalizeTopology(ctx, topology); err != nil {
				return ctrl.Result{}, err
			}
			controllerutil.RemoveFinalizer(topology, topologyFinalizer)
			if err := r.Update(ctx, topology); err != nil {
				return ctrl.Result{}, err
			}
		}
		return ctrl.Result{}, nil
	}

	// Add finalizer if not present
	if !controllerutil.ContainsFinalizer(topology, topologyFinalizer) {
		controllerutil.AddFinalizer(topology, topologyFinalizer)
		if err := r.Update(ctx, topology); err != nil {
			return ctrl.Result{}, err
		}
	}

	// Initialize status if needed
	if topology.Status.Phase == "" {
		topology.Status.Phase = "Creating"
		topology.Status.ObservedGeneration = topology.Generation
		if err := r.Status().Update(ctx, topology); err != nil {
			return ctrl.Result{}, err
		}
	}

	// Create topology namespace
	topologyNs := fmt.Sprintf("topology-%s", topology.Name)
	if err := r.reconcileNamespace(ctx, topology, topologyNs); err != nil {
		log.Error(err, "Failed to reconcile namespace")
		r.setCondition(ctx, topology, "Available", metav1.ConditionFalse, "NamespaceError", err.Error())
		return ctrl.Result{RequeueAfter: 30 * time.Second}, err
	}

	topology.Status.Namespace = topologyNs

	// Create NetworkAttachmentDefinitions for links
	if err := r.reconcileNetworkAttachments(ctx, topology, topologyNs); err != nil {
		log.Error(err, "Failed to reconcile network attachments")
		r.setCondition(ctx, topology, "Available", metav1.ConditionFalse, "NetworkError", err.Error())
		return ctrl.Result{RequeueAfter: 30 * time.Second}, err
	}

	// Create ConfigMaps, StatefulSets, and Services for each agent
	agentStatuses := []asiv1alpha1.AgentStatus{}
	for _, agent := range topology.Spec.Agents {
		status := asiv1alpha1.AgentStatus{
			Name:  agent.Name,
			Phase: "Pending",
		}

		// Create ConfigMap with agent configuration
		if err := r.reconcileAgentConfig(ctx, topology, topologyNs, agent); err != nil {
			log.Error(err, "Failed to reconcile agent config", "agent", agent.Name)
			status.Phase = "Failed"
			status.Message = fmt.Sprintf("Config error: %v", err)
			agentStatuses = append(agentStatuses, status)
			continue
		}

		// Create StatefulSet for agent
		if err := r.reconcileAgentStatefulSet(ctx, topology, topologyNs, agent); err != nil {
			log.Error(err, "Failed to reconcile agent StatefulSet", "agent", agent.Name)
			status.Phase = "Failed"
			status.Message = fmt.Sprintf("StatefulSet error: %v", err)
			agentStatuses = append(agentStatuses, status)
			continue
		}

		// Create Service to expose agent dashboard
		if err := r.reconcileAgentService(ctx, topology, topologyNs, agent); err != nil {
			log.Error(err, "Failed to reconcile agent service", "agent", agent.Name)
			status.Phase = "Failed"
			status.Message = fmt.Sprintf("Service error: %v", err)
			agentStatuses = append(agentStatuses, status)
			continue
		}

		status.Phase = "Running"
		status.PodName = fmt.Sprintf("%s-0", agent.Name)
		status.DashboardURL = fmt.Sprintf("http://%s.%s.svc.cluster.local:8080", agent.Name, topologyNs)
		status.Ready = true
		agentStatuses = append(agentStatuses, status)
	}

	// Update status
	topology.Status.AgentStatuses = agentStatuses
	topology.Status.Phase = "Running"
	topology.Status.ObservedGeneration = topology.Generation
	r.setCondition(ctx, topology, "Available", metav1.ConditionTrue, "TopologyReady", "All agents are running")

	if err := r.Status().Update(ctx, topology); err != nil {
		log.Error(err, "Failed to update topology status")
		return ctrl.Result{}, err
	}

	log.Info("Successfully reconciled AgentTopology", "namespace", topologyNs, "agents", len(agentStatuses))
	return ctrl.Result{RequeueAfter: 5 * time.Minute}, nil
}

// finalizeTopology cleans up resources when a topology is deleted
func (r *AgentTopologyReconciler) finalizeTopology(ctx context.Context, topology *asiv1alpha1.AgentTopology) error {
	log := logf.FromContext(ctx)
	topologyNs := fmt.Sprintf("topology-%s", topology.Name)

	// Delete the topology namespace (cascades to all resources)
	ns := &corev1.Namespace{}
	if err := r.Get(ctx, types.NamespacedName{Name: topologyNs}, ns); err != nil {
		if errors.IsNotFound(err) {
			return nil
		}
		return err
	}

	log.Info("Deleting topology namespace", "namespace", topologyNs)
	if err := r.Delete(ctx, ns); err != nil && !errors.IsNotFound(err) {
		return err
	}

	return nil
}

// reconcileNamespace creates or updates the topology namespace
func (r *AgentTopologyReconciler) reconcileNamespace(ctx context.Context, topology *asiv1alpha1.AgentTopology, nsName string) error {
	ns := &corev1.Namespace{
		ObjectMeta: metav1.ObjectMeta{
			Name: nsName,
			Labels: map[string]string{
				"asi.anthropic.com/topology": topology.Name,
				"istio-injection":            "enabled", // Enable Istio sidecar injection
			},
		},
	}

	existingNs := &corev1.Namespace{}
	if err := r.Get(ctx, types.NamespacedName{Name: nsName}, existingNs); err != nil {
		if errors.IsNotFound(err) {
			if err := r.Create(ctx, ns); err != nil {
				return fmt.Errorf("failed to create namespace: %w", err)
			}
			return nil
		}
		return err
	}

	// Update labels if needed
	if existingNs.Labels == nil {
		existingNs.Labels = make(map[string]string)
	}
	existingNs.Labels["asi.anthropic.com/topology"] = topology.Name
	existingNs.Labels["istio-injection"] = "enabled"

	if err := r.Update(ctx, existingNs); err != nil {
		return fmt.Errorf("failed to update namespace: %w", err)
	}

	return nil
}

// reconcileNetworkAttachments creates NetworkAttachmentDefinitions for each link
func (r *AgentTopologyReconciler) reconcileNetworkAttachments(ctx context.Context, topology *asiv1alpha1.AgentTopology, namespace string) error {
	log := logf.FromContext(ctx)

	// Create a NetworkAttachmentDefinition for each link
	for linkIndex, link := range topology.Spec.Links {
		nadName := link.Name

		// Create bridge-based NAD for point-to-point link
		// Use host-local IPAM with a /24 subnet for each link (provides 254 usable IPs)
		// We'll override these IPs in the startup script
		// Each link gets its own subnet: 169.254.0.0/24, 169.254.1.0/24, 169.254.2.0/24, etc.
		// Bridge plugin creates a Linux bridge on the host that both pods connect to
		subnet := fmt.Sprintf("169.254.%d.0/24", linkIndex)
		bridgeName := fmt.Sprintf("asi-br-%d", linkIndex)

		nadConfig := fmt.Sprintf(`{
			"cniVersion": "0.3.1",
			"type": "bridge",
			"bridge": "%s",
			"isGateway": false,
			"ipMasq": false,
			"ipam": {
				"type": "host-local",
				"subnet": "%s"
			}
		}`, bridgeName, subnet)

		nad := map[string]interface{}{
			"apiVersion": "k8s.cni.cncf.io/v1",
			"kind":       "NetworkAttachmentDefinition",
			"metadata": map[string]interface{}{
				"name":      nadName,
				"namespace": namespace,
				"labels": map[string]string{
					"asi.anthropic.com/topology": topology.Name,
					"asi.anthropic.com/link":     link.Name,
				},
			},
			"spec": map[string]interface{}{
				"config": nadConfig,
			},
		}

		// Check if NAD exists
		existingNad := &unstructured.Unstructured{}
		existingNad.SetGroupVersionKind(schema.GroupVersionKind{
			Group:   "k8s.cni.cncf.io",
			Version: "v1",
			Kind:    "NetworkAttachmentDefinition",
		})
		err := r.Get(ctx, types.NamespacedName{Name: nadName, Namespace: namespace}, existingNad)

		if err != nil {
			if errors.IsNotFound(err) {
				// Create new NAD
				log.Info("Creating NetworkAttachmentDefinition", "name", nadName, "namespace", namespace)
				unstructuredNad := &unstructured.Unstructured{Object: nad}
				if err := r.Create(ctx, unstructuredNad); err != nil {
					return fmt.Errorf("failed to create NAD %s: %w", nadName, err)
				}
			} else {
				return err
			}
		}
	}

	return nil
}

// reconcileAgentConfig creates a ConfigMap with agent configuration
func (r *AgentTopologyReconciler) reconcileAgentConfig(ctx context.Context, topology *asiv1alpha1.AgentTopology, namespace string, agent asiv1alpha1.AgentSpec) error {
	configData := r.buildAgentConfig(agent)

	cm := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("%s-config", agent.Name),
			Namespace: namespace,
			Labels: map[string]string{
				"asi.anthropic.com/agent":    agent.Name,
				"asi.anthropic.com/topology": topology.Name,
			},
		},
		Data: configData,
	}

	existingCm := &corev1.ConfigMap{}
	if err := r.Get(ctx, types.NamespacedName{Name: cm.Name, Namespace: namespace}, existingCm); err != nil {
		if errors.IsNotFound(err) {
			return r.Create(ctx, cm)
		}
		return err
	}

	existingCm.Data = configData
	return r.Update(ctx, existingCm)
}

// buildAgentConfig creates configuration data for an agent
func (r *AgentTopologyReconciler) buildAgentConfig(agent asiv1alpha1.AgentSpec) map[string]string {
	config := make(map[string]string)

	// Add agent configuration (this would be expanded based on actual agent needs)
	config["agent.name"] = agent.Name

	if agent.LLM != nil {
		config["llm.model"] = agent.LLM.Model
		if agent.LLM.Profile != "" {
			config["llm.profile"] = agent.LLM.Profile
		}
		if agent.LLM.Temperature != "" {
			config["llm.temperature"] = agent.LLM.Temperature
		}
	}

	// Add interface configuration
	for i, iface := range agent.Interfaces {
		config[fmt.Sprintf("interface.%d.name", i)] = iface.Name
		config[fmt.Sprintf("interface.%d.type", i)] = iface.Type
		if len(iface.Addresses) > 0 {
			for j, addr := range iface.Addresses {
				config[fmt.Sprintf("interface.%d.address.%d", i, j)] = addr
			}
		}
	}

	// Add protocol configuration
	for i, proto := range agent.Protocols {
		config[fmt.Sprintf("protocol.%d.type", i)] = proto.Type
		for k, v := range proto.Config {
			config[fmt.Sprintf("protocol.%d.%s", i, k)] = v
		}
	}

	return config
}

// buildNetworkAnnotations creates Multus network annotations for an agent
func (r *AgentTopologyReconciler) buildNetworkAnnotations(topology *asiv1alpha1.AgentTopology, namespace string, agentName string) map[string]string {
	annotations := make(map[string]string)

	// Find all links where this agent is an endpoint
	networks := []string{}
	interfaceMapping := make(map[string]string) // interface -> nad name

	for _, link := range topology.Spec.Links {
		for _, endpoint := range link.Endpoints {
			if endpoint.Agent == agentName {
				// Add this NAD as a network attachment (without @interface to let Multus use net1, net2, net3)
				nadRef := fmt.Sprintf("%s/%s", namespace, link.Name)
				networks = append(networks, nadRef)
				interfaceMapping[endpoint.Interface] = link.Name
			}
		}
	}

	if len(networks) > 0 {
		// Join all NAD references with commas (shorthand notation)
		annotations["k8s.v1.cni.cncf.io/networks"] = strings.Join(networks, ", ")
	}

	return annotations
}

// reconcileAgentStatefulSet creates or updates a StatefulSet for an agent
func (r *AgentTopologyReconciler) reconcileAgentStatefulSet(ctx context.Context, topology *asiv1alpha1.AgentTopology, namespace string, agent asiv1alpha1.AgentSpec) error {
	image := agent.Image
	if image == "" {
		image = defaultAgentImage
	}

	// Build network annotations for Multus
	networkAnnotations := r.buildNetworkAnnotations(topology, namespace, agent.Name)

	replicas := int32(1)
	statefulSet := &appsv1.StatefulSet{
		ObjectMeta: metav1.ObjectMeta{
			Name:      agent.Name,
			Namespace: namespace,
			Labels: map[string]string{
				"asi.anthropic.com/agent":    agent.Name,
				"asi.anthropic.com/topology": topology.Name,
			},
		},
		Spec: appsv1.StatefulSetSpec{
			Replicas:    &replicas,
			ServiceName: agent.Name,
			Selector: &metav1.LabelSelector{
				MatchLabels: map[string]string{
					"asi.anthropic.com/agent": agent.Name,
				},
			},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: map[string]string{
						"asi.anthropic.com/agent":    agent.Name,
						"asi.anthropic.com/topology": topology.Name,
					},
					Annotations: networkAnnotations,
				},
				Spec: corev1.PodSpec{
					ServiceAccountName: "default",
					Containers: []corev1.Container{
						{
							Name:  "agent",
							Image: image,
							Ports: []corev1.ContainerPort{
								{
									Name:          "dashboard",
									ContainerPort: 8000,
									Protocol:      corev1.ProtocolTCP,
								},
								{
									Name:          "metrics",
									ContainerPort: 9090,
									Protocol:      corev1.ProtocolTCP,
								},
							},
							Env: []corev1.EnvVar{
								{
									Name:  "AGENT_NAME",
									Value: agent.Name,
								},
								{
									Name:  "TOPOLOGY_NAME",
									Value: topology.Name,
								},
							},
							VolumeMounts: []corev1.VolumeMount{
								{
									Name:      "config",
									MountPath: "/etc/asi",
								},
								{
									Name:      "data",
									MountPath: "/var/lib/asi",
								},
							},
							SecurityContext: &corev1.SecurityContext{
								Capabilities: &corev1.Capabilities{
									Add: []corev1.Capability{
										"NET_ADMIN", // Required for interface configuration
										"NET_RAW",   // Required for raw sockets (OSPF, etc.)
									},
								},
							},
						},
					},
					Volumes: []corev1.Volume{
						{
							Name: "config",
							VolumeSource: corev1.VolumeSource{
								ConfigMap: &corev1.ConfigMapVolumeSource{
									LocalObjectReference: corev1.LocalObjectReference{
										Name: fmt.Sprintf("%s-config", agent.Name),
									},
								},
							},
						},
					},
				},
			},
			VolumeClaimTemplates: []corev1.PersistentVolumeClaim{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name: "data",
					},
					Spec: corev1.PersistentVolumeClaimSpec{
						AccessModes: []corev1.PersistentVolumeAccessMode{
							corev1.ReadWriteOnce,
						},
						Resources: corev1.VolumeResourceRequirements{
							Requests: corev1.ResourceList{
								corev1.ResourceStorage: resource.MustParse("1Gi"),
							},
						},
					},
				},
			},
		},
	}

	existingSts := &appsv1.StatefulSet{}
	if err := r.Get(ctx, types.NamespacedName{Name: agent.Name, Namespace: namespace}, existingSts); err != nil {
		if errors.IsNotFound(err) {
			return r.Create(ctx, statefulSet)
		}
		return err
	}

	// Update the StatefulSet (simplified - in production would do proper comparison)
	existingSts.Spec = statefulSet.Spec
	return r.Update(ctx, existingSts)
}

// reconcileAgentService creates or updates a Service for an agent
func (r *AgentTopologyReconciler) reconcileAgentService(ctx context.Context, topology *asiv1alpha1.AgentTopology, namespace string, agent asiv1alpha1.AgentSpec) error {
	service := &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      agent.Name,
			Namespace: namespace,
			Labels: map[string]string{
				"asi.anthropic.com/agent":    agent.Name,
				"asi.anthropic.com/topology": topology.Name,
			},
		},
		Spec: corev1.ServiceSpec{
			Type: corev1.ServiceTypeClusterIP,
			Selector: map[string]string{
				"asi.anthropic.com/agent": agent.Name,
			},
			Ports: []corev1.ServicePort{
				{
					Name:       "dashboard",
					Port:       8080,
					TargetPort: intstr.FromInt(8080),
					Protocol:   corev1.ProtocolTCP,
				},
				{
					Name:       "metrics",
					Port:       9090,
					TargetPort: intstr.FromInt(9090),
					Protocol:   corev1.ProtocolTCP,
				},
			},
			ClusterIP: "None", // Headless service for StatefulSet
		},
	}

	existingSvc := &corev1.Service{}
	if err := r.Get(ctx, types.NamespacedName{Name: agent.Name, Namespace: namespace}, existingSvc); err != nil {
		if errors.IsNotFound(err) {
			return r.Create(ctx, service)
		}
		return err
	}

	// Update the service (simplified)
	existingSvc.Spec.Ports = service.Spec.Ports
	existingSvc.Spec.Selector = service.Spec.Selector
	return r.Update(ctx, existingSvc)
}

// setCondition sets a condition on the topology status
func (r *AgentTopologyReconciler) setCondition(ctx context.Context, topology *asiv1alpha1.AgentTopology, condType string, status metav1.ConditionStatus, reason, message string) {
	condition := metav1.Condition{
		Type:               condType,
		Status:             status,
		ObservedGeneration: topology.Generation,
		LastTransitionTime: metav1.Now(),
		Reason:             reason,
		Message:            message,
	}

	meta.SetStatusCondition(&topology.Status.Conditions, condition)
}

// SetupWithManager sets up the controller with the Manager.
func (r *AgentTopologyReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&asiv1alpha1.AgentTopology{}).
		Owns(&corev1.Namespace{}).
		Owns(&appsv1.StatefulSet{}).
		Owns(&corev1.Service{}).
		Owns(&corev1.ConfigMap{}).
		Named("agenttopology").
		Complete(r)
}
