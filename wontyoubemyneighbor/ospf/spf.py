"""
OSPF SPF (Shortest Path First) Calculation
RFC 2328 Section 16 - Calculation of the routing table
Uses Dijkstra's algorithm
"""

import logging
from typing import Dict, List, Optional
import networkx as nx
from ospf.lsdb import LinkStateDatabase, LSA
from ospf.constants import ROUTER_LSA, NETWORK_LSA, LINK_TYPE_PTP, LINK_TYPE_TRANSIT, LINK_TYPE_STUB

logger = logging.getLogger(__name__)


class RouteEntry:
    """
    Routing table entry
    """

    def __init__(self, destination: str, cost: int, next_hop: Optional[str], path: List[str]):
        """
        Initialize route entry

        Args:
            destination: Destination network/router
            cost: Total path cost
            next_hop: Next hop router ID or IP
            path: Full path to destination
        """
        self.destination = destination
        self.cost = cost
        self.next_hop = next_hop
        self.path = path

    def __repr__(self) -> str:
        return (f"Route(dest={self.destination}, "
                f"cost={self.cost}, "
                f"next_hop={self.next_hop})")


class SPFCalculator:
    """
    Calculate shortest path first using Dijkstra's algorithm
    RFC 2328 Section 16
    """

    def __init__(self, router_id: str, lsdb: LinkStateDatabase):
        """
        Initialize SPF calculator

        Args:
            router_id: This router's ID
            lsdb: Link State Database
        """
        self.router_id = router_id
        self.lsdb = lsdb
        self.routing_table: Dict[str, RouteEntry] = {}
        self.graph: Optional[nx.Graph] = None

        logger.info(f"Initialized SPF calculator for {router_id}")

    def calculate(self) -> Dict[str, RouteEntry]:
        """
        Run SPF algorithm and build routing table

        Returns:
            Dictionary of destination -> RouteEntry
        """
        logger.info(f"Starting SPF calculation for {self.router_id}")

        # Step 1: Build network graph from LSDB
        self.graph = self._build_graph()

        if not self.graph or self.router_id not in self.graph:
            logger.warning("Cannot run SPF - router not in graph")
            return {}

        # Step 2: Run Dijkstra from our router
        try:
            shortest_paths = nx.single_source_dijkstra_path(
                self.graph, self.router_id, weight='weight'
            )
            shortest_costs = nx.single_source_dijkstra_path_length(
                self.graph, self.router_id, weight='weight'
            )
        except Exception as e:
            logger.error(f"Dijkstra calculation failed: {e}")
            return {}

        # Step 3: Build routing table from shortest paths
        self.routing_table.clear()

        for dest, cost in shortest_costs.items():
            if dest == self.router_id:
                continue  # Skip self

            path = shortest_paths.get(dest, [])

            # Determine next hop
            if len(path) > 1:
                next_hop = path[1]  # Second node in path
            else:
                next_hop = None

            self.routing_table[dest] = RouteEntry(
                destination=dest,
                cost=cost,
                next_hop=next_hop,
                path=path
            )

        logger.info(f"SPF calculation complete: {len(self.routing_table)} routes")
        return self.routing_table

    def _build_graph(self) -> nx.Graph:
        """
        Build network graph from LSAs in LSDB

        Returns:
            NetworkX graph
        """
        graph = nx.Graph()

        # Process all LSAs
        for lsa in self.lsdb.get_all_lsas():
            if lsa.header.ls_type == ROUTER_LSA:
                self._process_router_lsa(graph, lsa)
            elif lsa.header.ls_type == NETWORK_LSA:
                self._process_network_lsa(graph, lsa)

        logger.debug(f"Built graph: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")
        return graph

    def _process_router_lsa(self, graph: nx.Graph, lsa: LSA):
        """
        Add router and its links to graph

        Args:
            graph: NetworkX graph
            lsa: Router LSA
        """
        router_id = lsa.header.advertising_router

        # Add router node
        if router_id not in graph:
            graph.add_node(router_id)

        # Process links if we have the body
        if not lsa.body:
            return

        logger.debug(f"Processing {len(lsa.body.links)} links from Router LSA {router_id}")
        for link in lsa.body.links:
            logger.debug(f"  Link: type={link.link_type}, id={link.link_id}, data={link.link_data}, metric={link.metric}")
            if link.link_type == LINK_TYPE_PTP:
                # Point-to-point link to another router
                neighbor_id = link.link_id
                cost = link.metric

                # Add edge between routers
                if neighbor_id not in graph:
                    graph.add_node(neighbor_id)

                graph.add_edge(router_id, neighbor_id, weight=cost)
                logger.debug(f"Added P2P link: {router_id} <-> {neighbor_id} (cost={cost})")

            elif link.link_type == LINK_TYPE_TRANSIT:
                # Transit network (has DR)
                network_id = link.link_id
                cost = link.metric

                # Add network node
                if network_id not in graph:
                    graph.add_node(network_id)

                # Connect router to network
                graph.add_edge(router_id, network_id, weight=cost)
                logger.debug(f"Added transit link: {router_id} -> {network_id} (cost={cost})")

            elif link.link_type == LINK_TYPE_STUB:
                # Stub network (no further routing)
                network_id = link.link_id
                cost = link.metric

                # Add stub network node
                if network_id not in graph:
                    graph.add_node(network_id)

                graph.add_edge(router_id, network_id, weight=cost)
                logger.debug(f"Added stub link: {router_id} -> {network_id} (cost={cost})")

    def _process_network_lsa(self, graph: nx.Graph, lsa: LSA):
        """
        Add transit network to graph

        Args:
            graph: NetworkX graph
            lsa: Network LSA
        """
        network_id = lsa.header.link_state_id

        # Add network node
        if network_id not in graph:
            graph.add_node(network_id)

        # Process attached routers if we have the body
        if not lsa.body:
            return

        # Connect all attached routers to network with cost 0
        for router_id in lsa.body.attached_routers:
            if router_id not in graph:
                graph.add_node(router_id)

            if not graph.has_edge(network_id, router_id):
                graph.add_edge(network_id, router_id, weight=0)
                logger.debug(f"Added network link: {network_id} <-> {router_id}")

    def get_route(self, destination: str) -> Optional[RouteEntry]:
        """
        Get route to specific destination

        Args:
            destination: Destination router ID or network

        Returns:
            RouteEntry or None if not found
        """
        return self.routing_table.get(destination)

    def get_all_routes(self) -> Dict[str, RouteEntry]:
        """
        Get all routes

        Returns:
            Dictionary of destination -> RouteEntry
        """
        return self.routing_table.copy()

    def print_routing_table(self):
        """
        Print routing table in human-readable format
        """
        print(f"\n{'='*70}")
        print(f"Routing Table for {self.router_id}")
        print(f"{'='*70}")
        print(f"{'Destination':<30} {'Cost':<10} {'Next Hop':<30}")
        print(f"{'-'*70}")

        if not self.routing_table:
            print("(empty)")
        else:
            for dest, entry in sorted(self.routing_table.items()):
                next_hop_str = entry.next_hop or "local"
                print(f"{dest:<30} {entry.cost:<10} {next_hop_str:<30}")

        print(f"{'='*70}\n")

    def get_statistics(self) -> Dict[str, int]:
        """
        Get SPF statistics

        Returns:
            Dictionary with statistics
        """
        stats = {
            'routes': len(self.routing_table),
            'nodes': self.graph.number_of_nodes() if self.graph else 0,
            'edges': self.graph.number_of_edges() if self.graph else 0,
            'lsas': self.lsdb.get_size()
        }
        return stats

    def __repr__(self) -> str:
        return f"SPFCalculator(router_id={self.router_id}, routes={len(self.routing_table)})"
