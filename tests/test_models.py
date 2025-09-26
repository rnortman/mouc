"""Tests for data models."""

from mouc.models import Entity, FeatureMap, FeatureMapMetadata, Link


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
            dependencies=["dep1", "dep2"],
            links=[
                "[DD-123](https://example.com/doc)",
                "jira:JIRA-456",
            ],
            tags=["tag1", "tag2"],
        )

        assert cap.type == "capability"
        assert cap.id == "test_cap"
        assert cap.name == "Test Capability"
        assert cap.dependencies == ["dep1", "dep2"]
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

        assert entity.dependencies == []
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
            dependencies=["cap1", "cap2"],
            links=["jira:STORY-123"],
            tags=["urgent"],
            meta={"requestor": "test_team"},
        )

        assert story.type == "user_story"
        assert story.id == "test_story"
        assert story.dependencies == ["cap1", "cap2"]
        assert story.meta["requestor"] == "test_team"

    def test_outcome_entity_creation(self) -> None:
        """Test creating an outcome entity."""
        outcome = Entity(
            type="outcome",
            id="test_outcome",
            name="Test Outcome",
            description="A test outcome",
            dependencies=["story1", "story2"],
            links=["jira:EPIC-123"],
            tags=["priority"],
            meta={"target_date": "2024-Q3"},
        )

        assert outcome.type == "outcome"
        assert outcome.id == "test_outcome"
        assert outcome.dependencies == ["story1", "story2"]
        assert outcome.meta["target_date"] == "2024-Q3"


class TestFeatureMap:
    """Test the FeatureMap model."""

    def test_feature_map_creation(self) -> None:
        """Test creating a feature map."""
        metadata = FeatureMapMetadata(version="1.0", team="test_team")

        cap1 = Entity(type="capability", id="cap1", name="Cap 1", description="Desc 1")
        cap2 = Entity(
            type="capability", id="cap2", name="Cap 2", description="Desc 2", dependencies=["cap1"]
        )

        story1 = Entity(
            type="user_story",
            id="story1",
            name="Story 1",
            description="Desc",
            dependencies=["cap2"],
        )

        outcome1 = Entity(
            type="outcome",
            id="outcome1",
            name="Outcome 1",
            description="Desc",
            dependencies=["story1"],
        )

        feature_map = FeatureMap(
            metadata=metadata,
            entities=[cap1, cap2, story1, outcome1],
        )

        assert len(feature_map.entities) == 4
        assert len(feature_map.get_entities_by_type("capability")) == 2
        assert len(feature_map.get_entities_by_type("user_story")) == 1
        assert len(feature_map.get_entities_by_type("outcome")) == 1
        assert feature_map.get_all_ids() == {"cap1", "cap2", "story1", "outcome1"}

    def test_get_dependents(self) -> None:
        """Test finding entity dependents."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(type="capability", id="cap1", name="Cap 1", description="Desc 1")
        cap2 = Entity(
            type="capability", id="cap2", name="Cap 2", description="Desc 2", dependencies=["cap1"]
        )
        cap3 = Entity(
            type="capability",
            id="cap3",
            name="Cap 3",
            description="Desc 3",
            dependencies=["cap1", "cap2"],
        )

        feature_map = FeatureMap(
            metadata=metadata,
            entities=[cap1, cap2, cap3],
        )

        assert set(feature_map.get_dependents("cap1")) == {"cap2", "cap3"}
        assert feature_map.get_dependents("cap2") == ["cap3"]
        assert feature_map.get_dependents("cap3") == []

    def test_get_story_dependents(self) -> None:
        """Test finding story dependents."""
        metadata = FeatureMapMetadata()

        story1 = Entity(type="user_story", id="story1", name="Story 1", description="Desc")
        story2 = Entity(type="user_story", id="story2", name="Story 2", description="Desc")

        outcome1 = Entity(
            type="outcome",
            id="outcome1",
            name="Outcome 1",
            description="Desc",
            dependencies=["story1"],
        )
        outcome2 = Entity(
            type="outcome",
            id="outcome2",
            name="Outcome 2",
            description="Desc",
            dependencies=["story1", "story2"],
        )

        feature_map = FeatureMap(
            metadata=metadata,
            entities=[story1, story2, outcome1, outcome2],
        )

        assert set(feature_map.get_dependents("story1")) == {"outcome1", "outcome2"}
        assert feature_map.get_dependents("story2") == ["outcome2"]

    def test_get_entity_by_id(self) -> None:
        """Test getting entities by ID."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(type="capability", id="cap1", name="Cap 1", description="Desc 1")
        story1 = Entity(type="user_story", id="story1", name="Story 1", description="Desc")
        outcome1 = Entity(type="outcome", id="outcome1", name="Outcome 1", description="Desc")

        feature_map = FeatureMap(
            metadata=metadata,
            entities=[cap1, story1, outcome1],
        )

        assert feature_map.get_entity_by_id("cap1") == cap1
        assert feature_map.get_entity_by_id("story1") == story1
        assert feature_map.get_entity_by_id("outcome1") == outcome1
        assert feature_map.get_entity_by_id("nonexistent") is None
