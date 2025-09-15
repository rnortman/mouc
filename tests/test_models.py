"""Tests for data models."""

from mouc.models import Capability, FeatureMap, FeatureMapMetadata, Link, Outcome, UserStory


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


class TestCapability:
    """Test the Capability model."""

    def test_capability_creation(self) -> None:
        """Test creating a capability."""
        cap = Capability(
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

        assert cap.id == "test_cap"
        assert cap.name == "Test Capability"
        assert cap.dependencies == ["dep1", "dep2"]
        assert len(cap.parsed_links) == 2
        assert cap.parsed_links[0].label == "DD-123"
        assert cap.parsed_links[0].url == "https://example.com/doc"
        assert cap.parsed_links[1].type == "jira"
        assert cap.parsed_links[1].label == "JIRA-456"

    def test_capability_defaults(self) -> None:
        """Test capability with default values."""
        cap = Capability(
            id="test_cap",
            name="Test Capability",
            description="A test capability",
        )

        assert cap.dependencies == []
        assert cap.links == []
        assert cap.parsed_links == []
        assert cap.tags == []

    def test_link_parsing(self) -> None:
        """Test link parsing."""
        # Test various link formats
        cap = Capability(
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


class TestUserStory:
    """Test the UserStory model."""

    def test_user_story_creation(self) -> None:
        """Test creating a user story."""
        story = UserStory(
            id="test_story",
            name="Test Story",
            description="A test story",
            requires=["cap1", "cap2"],
            requestor="test_team",
            links=["jira:STORY-123"],
            tags=["urgent"],
        )

        assert story.id == "test_story"
        assert story.requires == ["cap1", "cap2"]
        assert story.requestor == "test_team"


class TestOutcome:
    """Test the Outcome model."""

    def test_outcome_creation(self) -> None:
        """Test creating an outcome."""
        outcome = Outcome(
            id="test_outcome",
            name="Test Outcome",
            description="A test outcome",
            enables=["story1", "story2"],
            links=["jira:EPIC-123"],
            target_date="2024-Q3",
            tags=["priority"],
        )

        assert outcome.id == "test_outcome"
        assert outcome.enables == ["story1", "story2"]
        assert outcome.target_date == "2024-Q3"


class TestFeatureMap:
    """Test the FeatureMap model."""

    def test_feature_map_creation(self) -> None:
        """Test creating a feature map."""
        metadata = FeatureMapMetadata(version="1.0", team="test_team")

        cap1 = Capability(id="cap1", name="Cap 1", description="Desc 1")
        cap2 = Capability(id="cap2", name="Cap 2", description="Desc 2", dependencies=["cap1"])

        story1 = UserStory(id="story1", name="Story 1", description="Desc", requires=["cap2"])

        outcome1 = Outcome(id="outcome1", name="Outcome 1", description="Desc", enables=["story1"])

        feature_map = FeatureMap(
            metadata=metadata,
            capabilities={"cap1": cap1, "cap2": cap2},
            user_stories={"story1": story1},
            outcomes={"outcome1": outcome1},
        )

        assert len(feature_map.capabilities) == 2
        assert feature_map.get_all_ids() == {"cap1", "cap2", "story1", "outcome1"}

    def test_get_capability_dependents(self) -> None:
        """Test finding capability dependents."""
        metadata = FeatureMapMetadata()

        cap1 = Capability(id="cap1", name="Cap 1", description="Desc 1")
        cap2 = Capability(id="cap2", name="Cap 2", description="Desc 2", dependencies=["cap1"])
        cap3 = Capability(
            id="cap3", name="Cap 3", description="Desc 3", dependencies=["cap1", "cap2"]
        )

        feature_map = FeatureMap(
            metadata=metadata,
            capabilities={"cap1": cap1, "cap2": cap2, "cap3": cap3},
            user_stories={},
            outcomes={},
        )

        assert feature_map.get_capability_dependents("cap1") == ["cap2", "cap3"]
        assert feature_map.get_capability_dependents("cap2") == ["cap3"]
        assert feature_map.get_capability_dependents("cap3") == []

    def test_get_story_dependents(self) -> None:
        """Test finding story dependents."""
        metadata = FeatureMapMetadata()

        story1 = UserStory(id="story1", name="Story 1", description="Desc")
        story2 = UserStory(id="story2", name="Story 2", description="Desc")

        outcome1 = Outcome(id="outcome1", name="Outcome 1", description="Desc", enables=["story1"])
        outcome2 = Outcome(
            id="outcome2", name="Outcome 2", description="Desc", enables=["story1", "story2"]
        )

        feature_map = FeatureMap(
            metadata=metadata,
            capabilities={},
            user_stories={"story1": story1, "story2": story2},
            outcomes={"outcome1": outcome1, "outcome2": outcome2},
        )

        assert set(feature_map.get_story_dependents("story1")) == {"outcome1", "outcome2"}
        assert feature_map.get_story_dependents("story2") == ["outcome2"]
