"""
ZepEntityReadandfilterService
Read nodes from the Zep graph and filter out predefined entity type nodes
"""

import time
from typing import Dict, Any, List, Optional, Set, Callable, TypeVar
from dataclasses import dataclass, field

from zep_cloud.client import Zep

from ..config import Config
from ..utils.logger import get_logger
from ..utils.zep_paging import fetch_all_nodes, fetch_all_edges

logger = get_logger('mirofish.zep_entity_reader')

# useattypeReturnType
T = TypeVar('T')


@dataclass
class EntityNode:
    """EntitynodeDatastructure"""
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]
    # relevantedgeinformation
    related_edges: List[Dict[str, Any]] = field(default_factory=list)
    # relevantitshenodeinformation
    related_nodes: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "labels": self.labels,
            "summary": self.summary,
            "attributes": self.attributes,
            "related_edges": self.related_edges,
            "related_nodes": self.related_nodes,
        }
    
    def get_entity_type(self) -> Optional[str]:
        """Get the entity type (excluding the default Entity label)."""
        for label in self.labels:
            if label not in ["Entity", "Node"]:
                return label
        return None


@dataclass
class FilteredEntities:
    """filterAfterEntitycollectcombine"""
    entities: List[EntityNode]
    entity_types: Set[str]
    total_count: int
    filtered_count: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "entities": [e.to_dict() for e in self.entities],
            "entity_types": list(self.entity_types),
            "total_count": self.total_count,
            "filtered_count": self.filtered_count,
        }


class ZepEntityReader:
    """
    ZepEntityReadandfilterService
    
    mainwantFeatures:
    1. fromZepGraphReadhasnode
    2. Filter out predefined entity type nodes (nodes whose labels are not only Entity)
    3. GeteachEntityrelevantedgesumrelationnodeinformation
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or Config.ZEP_API_KEY
        if not self.api_key:
            raise ValueError("ZEP_API_KEY notConfiguration")
        
        self.client = Zep(api_key=self.api_key)
    
    def _call_with_retry(
        self, 
        func: Callable[[], T], 
        operation_name: str,
        max_retries: int = 3,
        initial_delay: float = 2.0
    ) -> T:
        """
        beltheavytestmechanismZep APIinvoke
        
        Args:
            func: the function to execute (a no-argument lambda or callable)
            operation_name: operation name, used for logging
            max_retries: maximum retry count (default 3, i.e. at most 3 attempts)
            initial_delay: Initiallatesecondnumber
            
        Returns:
            APIinvokeresult
        """
        last_exception = None
        delay = initial_delay
        
        for attempt in range(max_retries):
            try:
                return func()
            except Exception as e:
                last_exception = e
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Zep {operation_name} # {attempt + 1} test failed: {str(e)[:100]}, "
                        f"{delay:.1f}secondafter heavytest..."
                    )
                    time.sleep(delay)
                    delay *= 2  # numberexit
                else:
                    logger.error(f"Zep {operation_name} at {max_retries} testAfterstillfail: {str(e)}")
        
        raise last_exception
    
    def get_all_nodes(self, graph_id: str) -> List[Dict[str, Any]]:
        """
        Get all nodes of the graph (paginated retrieval)

        Args:
            graph_id: GraphID

        Returns:
            nodelist
        """
        logger.info(f"Get graph {graph_id} hasnode...")

        nodes = fetch_all_nodes(self.client, graph_id)

        nodes_data = []
        for node in nodes:
            nodes_data.append({
                "uuid": getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                "name": node.name or "",
                "labels": node.labels or [],
                "summary": node.summary or "",
                "attributes": node.attributes or {},
            })

        logger.info(f"Get {len(nodes_data)} node")
        return nodes_data

    def get_all_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        """
        Get all edges of the graph (paginated retrieval)

        Args:
            graph_id: GraphID

        Returns:
            edgelist
        """
        logger.info(f"Get graph {graph_id} hasedge...")

        edges = fetch_all_edges(self.client, graph_id)

        edges_data = []
        for edge in edges:
            edges_data.append({
                "uuid": getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', ''),
                "name": edge.name or "",
                "fact": edge.fact or "",
                "source_node_uuid": edge.source_node_uuid,
                "target_node_uuid": edge.target_node_uuid,
                "attributes": edge.attributes or {},
            })

        logger.info(f"Get {len(edges_data)} edgeedge")
        return edges_data
    
    def get_node_edges(self, node_uuid: str) -> List[Dict[str, Any]]:
        """
        Get the relevant edges of a given node (with retry mechanism)
        
        Args:
            node_uuid: nodeUUID
            
        Returns:
            edgelist
        """
        try:
            # useheavytestmechanisminvokeZep API
            edges = self._call_with_retry(
                func=lambda: self.client.graph.node.get_entity_edges(node_uuid=node_uuid),
                operation_name=f"Get nodeedge(node={node_uuid[:8]}...)"
            )
            
            edges_data = []
            for edge in edges:
                edges_data.append({
                    "uuid": getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', ''),
                    "name": edge.name or "",
                    "fact": edge.fact or "",
                    "source_node_uuid": edge.source_node_uuid,
                    "target_node_uuid": edge.target_node_uuid,
                    "attributes": edge.attributes or {},
                })
            
            return edges_data
        except Exception as e:
            logger.warning(f"Get node {node_uuid} edgefail: {str(e)}")
            return []
    
    def filter_defined_entities(
        self, 
        graph_id: str,
        defined_entity_types: Optional[List[str]] = None,
        enrich_with_edges: bool = True
    ) -> FilteredEntities:
        """
        outcombinepremustmeaningEntityTypenode
        
        Rules:
        - If a node's labels only contain "Entity", it means this entity does not match a predefined type; skip it
        - If a node's labels contain labels other than "Entity" and "Node", it matches a predefined type; keep it
        
        Args:
            graph_id: GraphID
            defined_entity_types: list of predefined entity types (optional; if provided, only keep these types)
            enrich_with_edges: whetherGeteachEntityrelevantedgeinformation
            
        Returns:
            FilteredEntities: filterAfterEntitycollectcombine
        """
        logger.info(f"startGraph {graph_id} Entity...")
        
        # Gethasnode
        all_nodes = self.get_all_nodes(graph_id)
        total_count = len(all_nodes)
        
        # Get all edges (used later for relationship lookup)
        all_edges = self.get_all_edges(graph_id) if enrich_with_edges else []
        
        # buildnodeUUIDtonodeData
        node_map = {n["uuid"]: n for n in all_nodes}
        
        # combineconditionEntity
        filtered_entities = []
        entity_types_found = set()
        
        for node in all_nodes:
            labels = node.get("labels", [])
            
            # NOTE: labels must contain something other than "Entity" and "Node"
            custom_labels = [l for l in labels if l not in ["Entity", "Node"]]
            
            if not custom_labels:
                # Only default labels; skip
                continue
            
            # If predefined types are specified, check for a match
            if defined_entity_types:
                matching_labels = [l for l in custom_labels if l in defined_entity_types]
                if not matching_labels:
                    continue
                entity_type = matching_labels[0]
            else:
                entity_type = custom_labels[0]
            
            entity_types_found.add(entity_type)
            
            # createEntitynodeobject
            entity = EntityNode(
                uuid=node["uuid"],
                name=node["name"],
                labels=labels,
                summary=node["summary"],
                attributes=node["attributes"],
            )
            
            # Getrelevantedgesumnode
            if enrich_with_edges:
                related_edges = []
                related_node_uuids = set()
                
                for edge in all_edges:
                    if edge["source_node_uuid"] == node["uuid"]:
                        related_edges.append({
                            "direction": "outgoing",
                            "edge_name": edge["name"],
                            "fact": edge["fact"],
                            "target_node_uuid": edge["target_node_uuid"],
                        })
                        related_node_uuids.add(edge["target_node_uuid"])
                    elif edge["target_node_uuid"] == node["uuid"]:
                        related_edges.append({
                            "direction": "incoming",
                            "edge_name": edge["name"],
                            "fact": edge["fact"],
                            "source_node_uuid": edge["source_node_uuid"],
                        })
                        related_node_uuids.add(edge["source_node_uuid"])
                
                entity.related_edges = related_edges
                
                # Getrelationnodebasicinformation
                related_nodes = []
                for related_uuid in related_node_uuids:
                    if related_uuid in node_map:
                        related_node = node_map[related_uuid]
                        related_nodes.append({
                            "uuid": related_node["uuid"],
                            "name": related_node["name"],
                            "labels": related_node["labels"],
                            "summary": related_node.get("summary", ""),
                        })
                
                entity.related_nodes = related_nodes
            
            filtered_entities.append(entity)
        
        logger.info(f"complete: node {total_count}, combinecondition {len(filtered_entities)}, "
                   f"EntityType: {entity_types_found}")
        
        return FilteredEntities(
            entities=filtered_entities,
            entity_types=entity_types_found,
            total_count=total_count,
            filtered_count=len(filtered_entities),
        )
    
    def get_entity_with_context(
        self, 
        graph_id: str, 
        entity_uuid: str
    ) -> Optional[EntityNode]:
        """
        Get a single entity plus its full context (edges and related nodes, with retry mechanism)
        
        Args:
            graph_id: GraphID
            entity_uuid: EntityUUID
            
        Returns:
            EntityNodeorNone
        """
        try:
            # useheavytestmechanismGet node
            node = self._call_with_retry(
                func=lambda: self.client.graph.node.get(uuid_=entity_uuid),
                operation_name=f"Get nodeemotion(uuid={entity_uuid[:8]}...)"
            )
            
            if not node:
                return None
            
            # Get nodeedge
            edges = self.get_node_edges(entity_uuid)
            
            # Gethasnodeuseatrelationfind
            all_nodes = self.get_all_nodes(graph_id)
            node_map = {n["uuid"]: n for n in all_nodes}
            
            # Processrelevantedgesumnode
            related_edges = []
            related_node_uuids = set()
            
            for edge in edges:
                if edge["source_node_uuid"] == entity_uuid:
                    related_edges.append({
                        "direction": "outgoing",
                        "edge_name": edge["name"],
                        "fact": edge["fact"],
                        "target_node_uuid": edge["target_node_uuid"],
                    })
                    related_node_uuids.add(edge["target_node_uuid"])
                else:
                    related_edges.append({
                        "direction": "incoming",
                        "edge_name": edge["name"],
                        "fact": edge["fact"],
                        "source_node_uuid": edge["source_node_uuid"],
                    })
                    related_node_uuids.add(edge["source_node_uuid"])
            
            # Getrelationnodeinformation
            related_nodes = []
            for related_uuid in related_node_uuids:
                if related_uuid in node_map:
                    related_node = node_map[related_uuid]
                    related_nodes.append({
                        "uuid": related_node["uuid"],
                        "name": related_node["name"],
                        "labels": related_node["labels"],
                        "summary": related_node.get("summary", ""),
                    })
            
            return EntityNode(
                uuid=getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                name=node.name or "",
                labels=node.labels or [],
                summary=node.summary or "",
                attributes=node.attributes or {},
                related_edges=related_edges,
                related_nodes=related_nodes,
            )
            
        except Exception as e:
            logger.error(f"GetEntity {entity_uuid} fail: {str(e)}")
            return None
    
    def get_entities_by_type(
        self, 
        graph_id: str, 
        entity_type: str,
        enrich_with_edges: bool = True
    ) -> List[EntityNode]:
        """
        GetmustTypehasEntity
        
        Args:
            graph_id: GraphID
            entity_type: entity type (e.g. "Student", "PublicFigure")
            enrich_with_edges: whetherGetrelevantedgeinformation
            
        Returns:
            Entitylist
        """
        result = self.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=[entity_type],
            enrich_with_edges=enrich_with_edges
        )
        return result.entities


