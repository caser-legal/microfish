"""
Ontology Generation Service
Step 1: Analyze the text content and generate the Entity and Relationship Type definitions used for the simulation.
"""

import json
from typing import Dict, Any, List, Optional
from ..utils.llm_client import LLMClient


# Ontology generation system prompt
ONTOLOGY_SYSTEM_PROMPT = """You are a Knowledge Graph ontology design expert. Your task is to analyze the given text content and simulation requirements, and design the Entity Types and Relationship Types for a multi-agent simulation.

**Important: You must output valid JSON data, and do not output any other content.**

## Core Task Background

We are building a **multi-agent simulation system**. In this system:
- Entities become autonomous agents, or the objects those agents act upon.
- Agents observe shared world state, choose actions, and change that state.
- We need to model who participates, what they act on, and how they relate.

**Entities must be concrete participants or concrete objects that can be acted upon.**

**Can be entities**:
- Specific persons (decision makers, stakeholders, experts, ordinary participants)
- Companies, organizations, institutions, agencies, media outlets
- Groups that act with one voice (a committee, a trading desk, a fan community)
- Concrete objects the simulation acts on (a market, an instrument, a proposal,
  a budget, a territory, a resource, a policy document)

**Cannot be entities**:
- Abstract qualities (e.g. "Sentiment", "emotion", "momentum", "volatility")
- Topics of discussion (e.g. "education reform", "market conditions")
- Viewpoints or stances (e.g. "support", "opposition", "bullish")

The distinction that matters: an entity is something that either *acts* or is
*acted upon*. "Volatility" is neither. "The BTC-100K market" is acted upon.
"A market maker" acts.

## Output Format

Please output JSON in the following structure:

```json
{
    "entity_types": [
        {
            "name": "EntityTypeName (e.g., PascalCase)",
            "description": "Short description (no more than 100 characters)",
            "attributes": [
                {
                    "name": "attribute_name (e.g., snake_case)",
                    "type": "text",
                    "description": "Attribute description"
                }
            ],
            "examples": ["exampleEntity1", "exampleEntity2"]
        }
    ],
    "edge_types": [
        {
            "name": "RELATION_TYPE_NAME (e.g., UPPER_SNAKE_CASE)",
            "description": "Short description (no more than 100 characters)",
            "source_targets": [
                {"source": "EntityType", "target": "TargetEntityType"}
            ],
            "attributes": []
        }
    ],
    "analysis_summary": "A brief analysis of the text content (concise)"
}
```

## Design Guide

### 1. Entity Type Design

Provide up to 10 entity types. Use the number the domain actually needs; do not pad the ontology with irrelevant types. For social domains, people and organizations are valid entities. For markets, include concrete objects such as markets, instruments, order books, positions and wallets. For allocation, include concrete resources, pools, claims and stakeholders. For any other domain, identify concrete actors and objects that can be changed by an action.

Abstract concepts such as sentiment, volatility, momentum, fairness and opposition are not entities. Represent them as attributes, metrics or edges.

**Count limit: at most 10 entity types.**

Do not force a hierarchy or base types. Choose concrete actors and concrete objects that this domain actually uses.

Legacy base-type guidance (not mandatory): A. **Base types**:
   - `Person`: The base type for any individual person. When a person does not fit a more specific person type, use this type.
   - `Organization`: The base type for any organization. When an organization does not fit a more specific organization type, use this type.

B. **Specific types (8, designed based on the text content)**:
   - Based on the main roles/characters appearing in the text, design more specific types.
   - Example: If the text is about an academic event, you can have `Student`, `Professor`, `University`.
   - Example: If the text is about a business event, you can have `Company`, `CEO`, `Employee`.

**Why base types are needed**:
- The text will mention various individuals, such as "primary/secondary school teachers", "passersby", "some netizen".
- If no specific type matches, they should be placed in `Person`.
- By the same logic, small organizations, ad-hoc groups, etc. should be placed in `Organization`.

**Specific type design principles**:
- Identify the high-frequency or key role types from the text.
- Each specific type should have explicit relationships.
- The description must clearly distinguish this type from the base type.

### 2. Relationship Type Design

- Count: 6-10.
- Relationships should be links that actually exist in reality.
- Relationship source_targets must define entity types.

### 3. Attribute Design

- 1-3 key attributes per entity type.
- **Reserved**: Attribute names cannot use `name`, `uuid`, `group_id`, `created_at`, `summary` (these are system reserved words).
- Recommended: `full_name`, `title`, `role`, `position`, `location`, `description`, etc.

## Entity Type Reference

**People (specific)**:
- Student: learner
- Professor: teacher / researcher
- Journalist: reporter
- Celebrity: influencer
- Executive: executive
- Official: government official
- Lawyer: legal professional
- Doctor: medical doctor

**People (base)**:
- Person: any individual person (used when not fitting a specific type)

**Organization (specific)**:
- University: higher-education institution
- Company: company / enterprise
- GovernmentAgency: government agency
- MediaOutlet: media organization
- Hospital: medical institution
- School: primary/secondary school
- NGO: non-governmental organization

**Organization (base)**:
- Organization: any organization (used when not fitting a specific type)

## Relationship Type Reference

- WORKS_FOR: works at
- STUDIES_AT: studies at
- AFFILIATED_WITH: affiliated with
- REPRESENTS: represents
- REGULATES: regulates
- REPORTS_ON: reports on
- COMMENTS_ON: comments on
- RESPONDS_TO: responds to
- SUPPORTS: supports
- OPPOSES: opposes
- COLLABORATES_WITH: collaborates with
- COMPETES_WITH: competes with
"""


class OntologyGenerator:
    """
    Ontology Generator
    Analyzes the text content and generates the Entity and Relationship Type definitions.
    """

    # Number of attempts for ontology generation before giving up
    MAX_ATTEMPTS = 3

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()

    def generate(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate the ontology definition.

        Args:
            document_texts: list of document texts
            simulation_requirement: description of the simulation requirements
            additional_context: additional context

        Returns:
            The ontology definition (entity_types, edge_types, etc.)
        """
        # Build the user message
        user_message = self._build_user_message(
            document_texts,
            simulation_requirement,
            additional_context
        )

        messages = [
            {"role": "system", "content": ONTOLOGY_SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ]

        # Call the LLM. No max_tokens: the ontology is 10 entity types plus
        # 6-10 edge types with attributes, which overflows a 4096-token cap and
        # comes back as truncated, unparseable JSON.
        last_error = None
        for attempt in range(self.MAX_ATTEMPTS):
            try:
                result = self.llm_client.chat_json(
                    messages=messages,
                    temperature=0.3
                )
                # Validate and post-process
                return self._validate_and_process(result)
            except ValueError as e:
                last_error = e

        raise ValueError(
            f"Ontology generation failed after {self.MAX_ATTEMPTS} attempts. "
            f"Last error: {last_error}"
        )

    # Maximum text length passed to the LLM (50,000 characters)
    MAX_TEXT_LENGTH_FOR_LLM = 50000

    def _build_user_message(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str]
    ) -> str:
        """Build the user message."""

        # Combine the texts
        combined_text = "\n\n---\n\n".join(document_texts)
        original_length = len(combined_text)

        # If the text exceeds 50,000 characters, truncate (only affects the content sent to the LLM, not graph construction)
        if len(combined_text) > self.MAX_TEXT_LENGTH_FOR_LLM:
            combined_text = combined_text[:self.MAX_TEXT_LENGTH_FOR_LLM]
            combined_text += f"\n\n...(Original document is {original_length} characters; only the first {self.MAX_TEXT_LENGTH_FOR_LLM} characters are used for ontology analysis)..."

        message = f"""## Simulation Requirements

{simulation_requirement}

## Document Content

{combined_text}
"""

        if additional_context:
            message += f"""
## Additional Context

{additional_context}
"""

        message += """
Based on the above content, design the Entity Types and Relationship Types for this simulation domain.

**Rules you must follow**:
1. Provide up to 10 entity types; use only types that the domain actually needs.
2. Include concrete actors and concrete objects that agents act on. Do not force Person and Organization into non-social domains.
3. Abstract concepts such as sentiment, volatility, momentum, fairness and opposition are not entities.
4. Relationship source_targets must reference generated entity types.
5. Attribute names cannot use reserved words such as name, uuid, group_id; use full_name, org_name, etc. instead.
6. Write all output in English.
"""

        return message

    def _validate_and_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and post-process the result."""

        # Ensure required fields exist
        if "entity_types" not in result:
            result["entity_types"] = []
        if "edge_types" not in result:
            result["edge_types"] = []
        if "analysis_summary" not in result:
            result["analysis_summary"] = ""

        # Validate entity types
        for entity in result["entity_types"]:
            if "attributes" not in entity:
                entity["attributes"] = []
            if "examples" not in entity:
                entity["examples"] = []
            # Keep descriptions under 100 characters
            if len(entity.get("description", "")) > 100:
                entity["description"] = entity["description"][:97] + "..."

        # Validate relationship types
        for edge in result["edge_types"]:
            if "source_targets" not in edge:
                edge["source_targets"] = []
            if "attributes" not in edge:
                edge["attributes"] = []
            if len(edge.get("description", "")) > 100:
                edge["description"] = edge["description"][:97] + "..."

        # Zep API limits: at most 10 custom entity types, at most 10 custom edge types
        MAX_ENTITY_TYPES = 10
        MAX_EDGE_TYPES = 10

        # Final safety cap (defensive)
        if len(result["entity_types"]) > MAX_ENTITY_TYPES:
            result["entity_types"] = result["entity_types"][:MAX_ENTITY_TYPES]

        if len(result["edge_types"]) > MAX_EDGE_TYPES:
            result["edge_types"] = result["edge_types"][:MAX_EDGE_TYPES]

        return result

    def generate_python_code(self, ontology: Dict[str, Any]) -> str:
        """
        Convert the ontology definition into Python code (similar to ontology.py).

        Args:
            ontology: the ontology definition

        Returns:
            Python code as a string
        """
        code_lines = [
            '"""',
            'Custom entity type definitions',
            'Auto-generated by MicroFish, used for sentiment simulation.',
            '"""',
            '',
            'from pydantic import Field',
            'from zep_cloud.external_clients.ontology import EntityModel, EntityText, EdgeModel',
            '',
            '',
            '# ============== Entity Type Definitions ==============',
            '',
        ]

        # Generate entity types
        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            desc = entity.get("description", f"A {name} entity.")

            code_lines.append(f'class {name}(EntityModel):')
            code_lines.append(f'    """{desc}"""')

            attrs = entity.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')

            code_lines.append('')
            code_lines.append('')

        code_lines.append('# ============== Relationship Type Definitions ==============')
        code_lines.append('')

        # Generate relationship types
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            # Convert to a PascalCase class name
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            desc = edge.get("description", f"A {name} relationship.")

            code_lines.append(f'class {class_name}(EdgeModel):')
            code_lines.append(f'    """{desc}"""')

            attrs = edge.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')

            code_lines.append('')
            code_lines.append('')

        # Generate the type dicts
        code_lines.append('# ============== Type Configuration ==============')
        code_lines.append('')
        code_lines.append('ENTITY_TYPES = {')
        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            code_lines.append(f'    "{name}": {name},')
        code_lines.append('}')
        code_lines.append('')
        code_lines.append('EDGE_TYPES = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            code_lines.append(f'    "{name}": {class_name},')
        code_lines.append('}')
        code_lines.append('')

        # Generate edge source_targets
        code_lines.append('EDGE_SOURCE_TARGETS = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            source_targets = edge.get("source_targets", [])
            if source_targets:
                st_list = ', '.join([
                    f'{{"source": "{st.get("source", "Entity")}", "target": "{st.get("target", "Entity")}"}}'
                    for st in source_targets
                ])
                code_lines.append(f'    "{name}": [{st_list}],')
        code_lines.append('}')

        return '\n'.join(code_lines)
