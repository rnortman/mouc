"""Tests for YAML formatting preservation during jira sync write-back."""

from __future__ import annotations

from pathlib import Path

from mouc.jira_cli import write_feature_map
from mouc.parser import FeatureMapParser

# pyright: reportPrivateUsage=false


def test_flow_style_list_in_meta_preserved(tmp_path: Path) -> None:
    """Test that flow-style lists inside meta are preserved during write-back."""
    test_file = tmp_path / "flow_style.yaml"
    test_file.write_text("""metadata:
  version: '1.0'

capabilities:
  test-1:
    name: Test Entity
    description: Test
    meta:
      status: not_started
      resources: ['user1', 'user2']
""")

    parser = FeatureMapParser()
    feature_map = parser.parse_file(test_file)

    # Modify meta to trigger write
    feature_map.entities[0].meta["status"] = "in_progress"

    # Write back
    write_feature_map(test_file, feature_map)

    # Read back and check formatting is preserved
    result = test_file.read_text()

    # Flow-style list should be preserved, not converted to block style
    # Should be: resources: ['user1', 'user2'] or resources: [user1, user2]
    # Should NOT be:
    #   resources:
    #   - user1
    #   - user2
    assert "resources:\n" not in result or "resources: [" in result, (
        f"Flow-style list was converted to block style:\n{result}"
    )


def test_no_meta_stays_no_meta(tmp_path: Path) -> None:
    """Test that entities without meta field don't get meta: {} added."""
    test_file = tmp_path / "no_meta.yaml"
    test_file.write_text("""metadata:
  version: '1.0'

capabilities:
  test-1:
    name: Entity with meta
    description: Test
    meta:
      status: not_started
  test-2:
    name: Entity without meta
    description: No meta field at all
""")

    parser = FeatureMapParser()
    feature_map = parser.parse_file(test_file)

    # Write back without changing anything
    write_feature_map(test_file, feature_map)

    # Read back and check test-2 still has no meta
    result = test_file.read_text()

    # test-2 should not have meta: {} added
    lines = result.split("\n")
    test2_section: list[str] = []
    in_test2 = False
    for line in lines:
        if "test-2:" in line:
            in_test2 = True
        elif in_test2:
            if line.strip() and not line.startswith("  "):
                break
            test2_section.append(line)

    test2_text = "\n".join(test2_section)
    assert "meta:" not in test2_text, f"Entity without meta got meta: {{}} added:\n{result}"
