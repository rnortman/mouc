"""Tests for data models."""

from mouc.models import (
    DAYS_PER_MONTH,
    DAYS_PER_WEEK,
    Dependency,
    Entity,
    FeatureMap,
    FeatureMapMetadata,
    JiraSyncMetadata,
    Link,
)
from mouc.parser import resolve_graph_edges


class TestDependency:
    """Test the Dependency model."""

    def test_parse_simple(self) -> None:
        """Test parsing a simple dependency without lag."""
        dep = Dependency.parse("task_a")
        assert dep.entity_id == "task_a"
        assert dep.lag_days == 0.0

    def test_parse_with_days_lag(self) -> None:
        """Test parsing a dependency with days lag."""
        dep = Dependency.parse("task_a + 5d")
        assert dep.entity_id == "task_a"
        assert dep.lag_days == 5.0

    def test_parse_with_weeks_lag(self) -> None:
        """Test parsing a dependency with weeks lag."""
        dep = Dependency.parse("task_a + 2w")
        assert dep.entity_id == "task_a"
        assert dep.lag_days == 2 * DAYS_PER_WEEK

    def test_parse_with_months_lag(self) -> None:
        """Test parsing a dependency with months lag."""
        dep = Dependency.parse("task_a + 1m")
        assert dep.entity_id == "task_a"
        assert dep.lag_days == DAYS_PER_MONTH

    def test_parse_with_fractional_lag(self) -> None:
        """Test parsing a dependency with fractional lag."""
        dep = Dependency.parse("task_a + 1.5w")
        assert dep.entity_id == "task_a"
        assert dep.lag_days == 1.5 * DAYS_PER_WEEK

    def test_parse_with_whitespace(self) -> None:
        """Test parsing handles various whitespace."""
        dep1 = Dependency.parse("  task_a  +  3d  ")
        assert dep1.entity_id == "task_a"
        assert dep1.lag_days == 3.0

        dep2 = Dependency.parse("task_a+1w")
        assert dep2.entity_id == "task_a"
        assert dep2.lag_days == DAYS_PER_WEEK

    def test_str_no_lag(self) -> None:
        """Test string representation without lag."""
        dep = Dependency(entity_id="task_a", lag_days=0.0)
        assert str(dep) == "task_a"

    def test_str_with_days(self) -> None:
        """Test string representation with days."""
        dep = Dependency(entity_id="task_a", lag_days=5.0)
        assert str(dep) == "task_a + 5d"

    def test_str_with_weeks(self) -> None:
        """Test string representation with weeks."""
        dep = Dependency(entity_id="task_a", lag_days=14.0)
        assert str(dep) == "task_a + 2w"

    def test_str_with_months(self) -> None:
        """Test string representation with months."""
        dep = Dependency(entity_id="task_a", lag_days=60.0)
        assert str(dep) == "task_a + 2m"

    def test_equality(self) -> None:
        """Test Dependency equality."""
        dep1 = Dependency(entity_id="task_a", lag_days=7.0)
        dep2 = Dependency(entity_id="task_a", lag_days=7.0)
        dep3 = Dependency(entity_id="task_a", lag_days=14.0)
        dep4 = Dependency(entity_id="task_b", lag_days=7.0)

        assert dep1 == dep2
        assert dep1 != dep3
        assert dep1 != dep4

    def test_hashable(self) -> None:
        """Test Dependency is hashable for use in sets."""
        dep1 = Dependency(entity_id="task_a", lag_days=7.0)
        dep2 = Dependency(entity_id="task_a", lag_days=7.0)
        dep3 = Dependency(entity_id="task_b", lag_days=7.0)

        deps = {dep1, dep2, dep3}
        assert len(deps) == 2  # dep1 and dep2 are equal

    def test_roundtrip(self) -> None:
        """Test parsing and string conversion roundtrip."""
        original = "my_task + 3w"
        dep = Dependency.parse(original)
        assert str(dep) == original


class TestLink:
    """Test the Link model."""

    def test_link_parse_markdown(self) -> None:
        """Test parsing markdown links."""
        link = Link.parse("[DD-123](https://example.com/doc)")
        assert link.label == "DD-123"
        assert link.url == "https://example.com/doc"
        assert link.type is None

        # With type prefix
        link2 = Link.parse("design:[Design Doc](https://example.com)")
        assert link2.type == "design"
        assert link2.label == "Design Doc"
        assert link2.url == "https://example.com"

    def test_link_parse_typed_id(self) -> None:
        """Test parsing type-prefixed IDs."""
        link = Link.parse("jira:INFRA-456")
        assert link.type == "jira"
        assert link.label == "INFRA-456"
        assert link.url is None

    def test_link_parse_ticket_id(self) -> None:
        """Test parsing plain ticket IDs."""
        link = Link.parse("ABC-123")
        assert link.type == "ticket"
        assert link.label == "ABC-123"
        assert link.url is None

        # Not a ticket pattern
        link2 = Link.parse("some-text")
        assert link2.type is None
        assert link2.label == "some-text"
        assert link2.url is None

    def test_link_parse_url(self) -> None:
        """Test parsing plain URLs."""
        link = Link.parse("https://github.com/company/repo")
        assert link.type == "link"
        assert link.label == "github.com"
        assert link.url == "https://github.com/company/repo"


class TestEntity:
    """Test the Entity model."""

    def test_capability_entity_creation(self) -> None:
        """Test creating a capability entity."""
        cap = Entity(
            type="capability",
            id="test_cap",
            name="Test Capability",
            description="A test capability",
            requires={Dependency("dep1"), Dependency("dep2")},
            links=[
                "[DD-123](https://example.com/doc)",
                "jira:JIRA-456",
            ],
            tags=["tag1", "tag2"],
        )

        assert cap.type == "capability"
        assert cap.id == "test_cap"
        assert cap.name == "Test Capability"
        assert cap.requires_ids == {"dep1", "dep2"}
        assert len(cap.parsed_links) == 2
        assert cap.parsed_links[0].label == "DD-123"
        assert cap.parsed_links[0].url == "https://example.com/doc"
        assert cap.parsed_links[1].type == "jira"
        assert cap.parsed_links[1].label == "JIRA-456"

    def test_entity_defaults(self) -> None:
        """Test entity with default values."""
        entity = Entity(
            type="capability",
            id="test_cap",
            name="Test Capability",
            description="A test capability",
        )

        assert entity.requires == set()
        assert entity.enables == set()
        assert entity.links == []
        assert entity.parsed_links == []
        assert entity.tags == []
        assert entity.meta == {}

    def test_link_parsing(self) -> None:
        """Test link parsing."""
        # Test various link formats
        cap = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Desc",
            links=[
                "[DD-123](https://example.com/doc)",
                "design:[DD-456](https://example.com/doc2)",
                "jira:INFRA-789",
                "ABC-999",
                "https://github.com/company/repo",
            ],
        )

        links = cap.parsed_links
        assert len(links) == 5

        # Markdown link
        assert links[0].label == "DD-123"
        assert links[0].url == "https://example.com/doc"
        assert links[0].type is None

        # Type-prefixed markdown link
        assert links[1].type == "design"
        assert links[1].label == "DD-456"
        assert links[1].url == "https://example.com/doc2"

        # Type-prefixed ID
        assert links[2].type == "jira"
        assert links[2].label == "INFRA-789"
        assert links[2].url is None

        # Plain ticket ID
        assert links[3].type == "ticket"
        assert links[3].label == "ABC-999"
        assert links[3].url is None

        # Plain URL
        assert links[4].type == "link"
        assert links[4].label == "github.com"
        assert links[4].url == "https://github.com/company/repo"

    def test_user_story_entity_creation(self) -> None:
        """Test creating a user story entity."""
        story = Entity(
            type="user_story",
            id="test_story",
            name="Test Story",
            description="A test story",
            requires={Dependency("cap1"), Dependency("cap2")},
            links=["jira:STORY-123"],
            tags=["urgent"],
            meta={"requestor": "test_team"},
        )

        assert story.type == "user_story"
        assert story.id == "test_story"
        assert story.requires_ids == {"cap1", "cap2"}
        assert story.meta["requestor"] == "test_team"

    def test_outcome_entity_creation(self) -> None:
        """Test creating an outcome entity."""
        outcome = Entity(
            type="outcome",
            id="test_outcome",
            name="Test Outcome",
            description="A test outcome",
            requires={Dependency("story1"), Dependency("story2")},
            links=["jira:EPIC-123"],
            tags=["priority"],
            meta={"target_date": "2024-Q3"},
        )

        assert outcome.type == "outcome"
        assert outcome.id == "test_outcome"
        assert outcome.requires_ids == {"story1", "story2"}
        assert outcome.meta["target_date"] == "2024-Q3"


class TestFeatureMap:
    """Test the FeatureMap model."""

    def test_feature_map_creation(self) -> None:
        """Test creating a feature map."""
        metadata = FeatureMapMetadata(version="1.0", team="test_team")

        cap1 = Entity(type="capability", id="cap1", name="Cap 1", description="Desc 1")
        cap2 = Entity(
            type="capability",
            id="cap2",
            name="Cap 2",
            description="Desc 2",
            requires={Dependency("cap1")},
            enables={Dependency("story1")},
        )

        story1 = Entity(
            type="user_story",
            id="story1",
            name="Story 1",
            description="Desc",
            requires={Dependency("cap2")},
            enables={Dependency("outcome1")},
        )

        outcome1 = Entity(
            type="outcome",
            id="outcome1",
            name="Outcome 1",
            description="Desc",
            requires={Dependency("story1")},
        )

        entities = [cap1, cap2, story1, outcome1]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(
            metadata=metadata,
            entities=entities,
        )

        assert len(feature_map.entities) == 4
        assert len(feature_map.get_entities_by_type("capability")) == 2
        assert len(feature_map.get_entities_by_type("user_story")) == 1
        assert len(feature_map.get_entities_by_type("outcome")) == 1
        assert feature_map.get_all_ids() == {"cap1", "cap2", "story1", "outcome1"}

    def test_get_dependents(self) -> None:
        """Test finding entity dependents."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Desc 1",
            enables={Dependency("cap2"), Dependency("cap3")},
        )
        cap2 = Entity(
            type="capability",
            id="cap2",
            name="Cap 2",
            description="Desc 2",
            requires={Dependency("cap1")},
            enables={Dependency("cap3")},
        )
        cap3 = Entity(
            type="capability",
            id="cap3",
            name="Cap 3",
            description="Desc 3",
            requires={Dependency("cap1"), Dependency("cap2")},
        )

        entities = [cap1, cap2, cap3]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(
            metadata=metadata,
            entities=entities,
        )

        assert feature_map.get_dependents("cap1") == {"cap2", "cap3"}
        assert feature_map.get_dependents("cap2") == {"cap3"}
        assert feature_map.get_dependents("cap3") == set()

    def test_get_story_dependents(self) -> None:
        """Test finding story dependents."""
        metadata = FeatureMapMetadata()

        story1 = Entity(
            type="user_story",
            id="story1",
            name="Story 1",
            description="Desc",
            enables={Dependency("outcome1"), Dependency("outcome2")},
        )
        story2 = Entity(
            type="user_story",
            id="story2",
            name="Story 2",
            description="Desc",
            enables={Dependency("outcome2")},
        )

        outcome1 = Entity(
            type="outcome",
            id="outcome1",
            name="Outcome 1",
            description="Desc",
            requires={Dependency("story1")},
        )
        outcome2 = Entity(
            type="outcome",
            id="outcome2",
            name="Outcome 2",
            description="Desc",
            requires={Dependency("story1"), Dependency("story2")},
        )

        entities = [story1, story2, outcome1, outcome2]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(
            metadata=metadata,
            entities=entities,
        )

        assert feature_map.get_dependents("story1") == {"outcome1", "outcome2"}
        assert feature_map.get_dependents("story2") == {"outcome2"}

    def test_get_entity_by_id(self) -> None:
        """Test getting entities by ID."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(type="capability", id="cap1", name="Cap 1", description="Desc 1")
        story1 = Entity(type="user_story", id="story1", name="Story 1", description="Desc")
        outcome1 = Entity(type="outcome", id="outcome1", name="Outcome 1", description="Desc")

        entities = [cap1, story1, outcome1]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(
            metadata=metadata,
            entities=entities,
        )

        assert feature_map.get_entity_by_id("cap1") == cap1
        assert feature_map.get_entity_by_id("story1") == story1
        assert feature_map.get_entity_by_id("outcome1") == outcome1
        assert feature_map.get_entity_by_id("nonexistent") is None


class TestJiraSyncMetadata:
    """Test the JiraSyncMetadata model."""

    def test_from_dict_empty(self) -> None:
        """Test creating JiraSyncMetadata from None."""
        metadata = JiraSyncMetadata.from_dict(None)
        assert metadata.ignore_fields == []
        assert metadata.ignore_values == {}
        assert metadata.resolution_choices == {}

    def test_from_dict_with_data(self) -> None:
        """Test creating JiraSyncMetadata from dict."""
        data = {
            "ignore_fields": ["start_date", "effort"],
            "ignore_values": {"start_date": ["2024-12-01", "2023-06-15"]},
            "resolution_choices": {"end_date": "jira", "status": "mouc"},
        }
        metadata = JiraSyncMetadata.from_dict(data)
        assert metadata.ignore_fields == ["start_date", "effort"]
        assert metadata.ignore_values == {"start_date": ["2024-12-01", "2023-06-15"]}
        assert metadata.resolution_choices == {"end_date": "jira", "status": "mouc"}

    def test_to_dict_empty(self) -> None:
        """Test converting empty JiraSyncMetadata to dict."""
        metadata = JiraSyncMetadata()
        result = metadata.to_dict()
        assert result == {}

    def test_to_dict_with_data(self) -> None:
        """Test converting JiraSyncMetadata with data to dict."""
        metadata = JiraSyncMetadata(
            ignore_fields=["start_date"],
            ignore_values={"start_date": ["2024-12-01"]},
            resolution_choices={"effort": "mouc"},
        )
        result = metadata.to_dict()
        assert result == {
            "ignore_fields": ["start_date"],
            "ignore_values": {"start_date": ["2024-12-01"]},
            "resolution_choices": {"effort": "mouc"},
        }

    def test_entity_get_jira_sync_metadata(self) -> None:
        """Test getting JiraSyncMetadata from Entity."""
        entity = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Test",
            meta={
                "jira_sync": {
                    "ignore_fields": ["start_date"],
                    "resolution_choices": {"effort": "jira"},
                }
            },
        )
        jira_sync = entity.get_jira_sync_metadata()
        assert jira_sync.ignore_fields == ["start_date"]
        assert jira_sync.resolution_choices == {"effort": "jira"}

    def test_entity_get_jira_sync_metadata_empty(self) -> None:
        """Test getting JiraSyncMetadata from Entity with no jira_sync."""
        entity = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Test",
            meta={},
        )
        jira_sync = entity.get_jira_sync_metadata()
        assert jira_sync.ignore_fields == []
        assert jira_sync.ignore_values == {}
        assert jira_sync.resolution_choices == {}

    def test_entity_set_jira_sync_metadata(self) -> None:
        """Test setting JiraSyncMetadata on Entity."""
        entity = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Test",
            meta={},
        )
        jira_sync = JiraSyncMetadata(
            ignore_fields=["start_date"],
            ignore_values={"end_date": ["2025-12-31"]},
            resolution_choices={"status": "mouc"},
        )
        entity.set_jira_sync_metadata(jira_sync)
        assert "jira_sync" in entity.meta
        assert entity.meta["jira_sync"]["ignore_fields"] == ["start_date"]
        assert entity.meta["jira_sync"]["ignore_values"] == {"end_date": ["2025-12-31"]}
        assert entity.meta["jira_sync"]["resolution_choices"] == {"status": "mouc"}

    def test_entity_set_jira_sync_metadata_empty_removes(self) -> None:
        """Test that setting empty JiraSyncMetadata removes the jira_sync key."""
        entity = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Test",
            meta={"jira_sync": {"ignore_fields": ["start_date"]}},
        )
        jira_sync = JiraSyncMetadata()
        entity.set_jira_sync_metadata(jira_sync)
        assert "jira_sync" not in entity.meta
