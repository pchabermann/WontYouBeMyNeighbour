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

package v1alpha1

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// EDIT THIS FILE!  THIS IS SCAFFOLDING FOR YOU TO OWN!
// NOTE: json tags are required.  Any new fields you add must have json tags for the fields to be serialized.

// AgentTopologySpec defines the desired state of AgentTopology
type AgentTopologySpec struct {
	// Agents defines the network agents in this topology
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:MinItems=1
	Agents []AgentSpec `json:"agents"`

	// Links defines the point-to-point links between agents
	// +optional
	Links []LinkSpec `json:"links,omitempty"`
}

// AgentSpec defines a single network agent
type AgentSpec struct {
	// Name is the unique identifier for this agent
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:Pattern=^[a-z0-9]([-a-z0-9]*[a-z0-9])?$
	Name string `json:"name"`

	// Protocols defines the routing protocols enabled on this agent
	// +optional
	Protocols []ProtocolConfig `json:"protocols,omitempty"`

	// Interfaces defines the network interfaces on this agent
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:MinItems=1
	Interfaces []InterfaceConfig `json:"interfaces"`

	// LLM defines the LLM configuration for this agent
	// +optional
	LLM *LLMConfig `json:"llm,omitempty"`

	// MCPServers lists the MCP servers this agent should connect to
	// +optional
	MCPServers []string `json:"mcpServers,omitempty"`

	// Image specifies the container image for this agent (optional, uses default if not set)
	// +optional
	Image string `json:"image,omitempty"`

	// Resources defines compute resource requirements
	// +optional
	Resources *ResourceRequirements `json:"resources,omitempty"`
}

// ProtocolConfig defines configuration for a routing protocol
type ProtocolConfig struct {
	// Type is the protocol type (ospf, bgp, isis)
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:Enum=ospf;bgp;isis
	Type string `json:"type"`

	// Config contains protocol-specific configuration as key-value pairs
	// For OSPF: area, routerId, helloInterval, deadInterval, etc.
	// For BGP: asn, routerId, neighbors, etc.
	// For IS-IS: level, areaAddress, etc.
	// +optional
	Config map[string]string `json:"config,omitempty"`
}

// InterfaceConfig defines a network interface
type InterfaceConfig struct {
	// Name is the interface name (eth0, eth1, lo, etc.)
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:Pattern=^[a-z0-9]+$
	Name string `json:"name"`

	// Type is the interface type (ethernet, loopback)
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:Enum=ethernet;loopback
	Type string `json:"type"`

	// Addresses lists the IP addresses assigned to this interface
	// +optional
	Addresses []string `json:"addresses,omitempty"`

	// MTU is the maximum transmission unit
	// +optional
	// +kubebuilder:validation:Minimum=576
	// +kubebuilder:validation:Maximum=9216
	MTU *int32 `json:"mtu,omitempty"`
}

// LLMConfig defines LLM settings for an agent
type LLMConfig struct {
	// Model is the LLM model to use (claude-sonnet-4, claude-opus-4, etc.)
	// +kubebuilder:validation:Required
	Model string `json:"model"`

	// Profile is the system prompt/persona for this agent
	// +optional
	Profile string `json:"profile,omitempty"`

	// Temperature controls randomness in responses (0.0-1.0, serialized as string)
	// +optional
	// +kubebuilder:validation:Pattern=^0\.[0-9]+$|^1\.0+$
	Temperature string `json:"temperature,omitempty"`
}

// ResourceRequirements defines compute resource requirements
type ResourceRequirements struct {
	// CPU request in millicores
	// +optional
	CPURequest string `json:"cpuRequest,omitempty"`

	// Memory request (e.g., "256Mi", "1Gi")
	// +optional
	MemoryRequest string `json:"memoryRequest,omitempty"`

	// CPU limit in millicores
	// +optional
	CPULimit string `json:"cpuLimit,omitempty"`

	// Memory limit (e.g., "512Mi", "2Gi")
	// +optional
	MemoryLimit string `json:"memoryLimit,omitempty"`
}

// LinkSpec defines a point-to-point link between two agents
type LinkSpec struct {
	// Name is the unique identifier for this link
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:Pattern=^[a-z0-9]([-a-z0-9]*[a-z0-9])?$
	Name string `json:"name"`

	// Endpoints defines the two agent interfaces connected by this link
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:MinItems=2
	// +kubebuilder:validation:MaxItems=2
	Endpoints []LinkEndpoint `json:"endpoints"`

	// Subnet is the IPv6 subnet for SLAAC on this link (e.g., "fd00:0:1::/64")
	// +optional
	Subnet string `json:"subnet,omitempty"`

	// MTU is the maximum transmission unit for this link
	// +optional
	// +kubebuilder:validation:Minimum=576
	// +kubebuilder:validation:Maximum=9216
	MTU *int32 `json:"mtu,omitempty"`
}

// LinkEndpoint defines one end of a link
type LinkEndpoint struct {
	// Agent is the name of the agent
	// +kubebuilder:validation:Required
	Agent string `json:"agent"`

	// Interface is the name of the interface on the agent
	// +kubebuilder:validation:Required
	Interface string `json:"interface"`
}

// AgentTopologyStatus defines the observed state of AgentTopology.
type AgentTopologyStatus struct {
	// Namespace is the Kubernetes namespace created for this topology
	// +optional
	Namespace string `json:"namespace,omitempty"`

	// Phase represents the overall phase of the topology
	// +optional
	// +kubebuilder:validation:Enum=Pending;Creating;Running;Failed
	Phase string `json:"phase,omitempty"`

	// AgentStatuses tracks the status of each agent in the topology
	// +optional
	AgentStatuses []AgentStatus `json:"agentStatuses,omitempty"`

	// ObservedGeneration reflects the generation of the most recently observed AgentTopology
	// +optional
	ObservedGeneration int64 `json:"observedGeneration,omitempty"`

	// Conditions represent the current state of the AgentTopology resource.
	// Each condition has a unique type and reflects the status of a specific aspect of the resource.
	//
	// Standard condition types include:
	// - "Available": the resource is fully functional
	// - "Progressing": the resource is being created or updated
	// - "Degraded": the resource failed to reach or maintain its desired state
	//
	// The status of each condition is one of True, False, or Unknown.
	// +listType=map
	// +listMapKey=type
	// +optional
	Conditions []metav1.Condition `json:"conditions,omitempty"`
}

// AgentStatus represents the status of a single agent
type AgentStatus struct {
	// Name is the agent name
	// +kubebuilder:validation:Required
	Name string `json:"name"`

	// Phase represents the current phase of the agent
	// +optional
	// +kubebuilder:validation:Enum=Pending;Running;Failed;Unknown
	Phase string `json:"phase,omitempty"`

	// PodName is the Kubernetes pod name for this agent
	// +optional
	PodName string `json:"podName,omitempty"`

	// DashboardURL is the HTTP URL to access the agent's dashboard
	// +optional
	DashboardURL string `json:"dashboardURL,omitempty"`

	// Ready indicates if the agent is ready to serve traffic
	// +optional
	Ready bool `json:"ready,omitempty"`

	// Message contains a human-readable message about the agent status
	// +optional
	Message string `json:"message,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:resource:shortName=atopo;atopology
// +kubebuilder:printcolumn:name="Phase",type=string,JSONPath=`.status.phase`
// +kubebuilder:printcolumn:name="Namespace",type=string,JSONPath=`.status.namespace`
// +kubebuilder:printcolumn:name="Agents",type=integer,JSONPath=`.spec.agents[*].name`,description="Number of agents"
// +kubebuilder:printcolumn:name="Age",type=date,JSONPath=`.metadata.creationTimestamp`

// AgentTopology is the Schema for the agenttopologies API
type AgentTopology struct {
	metav1.TypeMeta `json:",inline"`

	// metadata is a standard object metadata
	// +optional
	metav1.ObjectMeta `json:"metadata,omitzero"`

	// spec defines the desired state of AgentTopology
	// +required
	Spec AgentTopologySpec `json:"spec"`

	// status defines the observed state of AgentTopology
	// +optional
	Status AgentTopologyStatus `json:"status,omitzero"`
}

// +kubebuilder:object:root=true

// AgentTopologyList contains a list of AgentTopology
type AgentTopologyList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitzero"`
	Items           []AgentTopology `json:"items"`
}

func init() {
	SchemeBuilder.Register(&AgentTopology{}, &AgentTopologyList{})
}
