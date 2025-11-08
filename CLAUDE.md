# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is **Mouc** (Mapping Outcomes User stories and Capabilities) - a lightweight system for tracking feature dependencies in software development. It maps relationships between technical capabilities, user stories, and organizational outcomes.

**Core Purpose**: Technical dependency tracker that answers "what depends on what" and "what blocks what" - not a project management system.

## Architecture

The system is built around a single YAML data model (`feature_map.yaml`) with three primary entity types:

1. **capabilities** - Technical work (infrastructure, middleware, platform features)
   - Have dependencies on other capabilities
   - Link to design docs and Jira tickets
   
2. **user_stories** - Internal customer requests from other engineering teams
   - Require specific capabilities to be complete
   - Usually have Jira tickets for visibility
   
3. **outcomes** - Business/organizational goals
   - Enabled by user stories
   - Always tracked in Jira for executive visibility

## Development Standards

Always unit test code using unit tests that are committed to the repo. Do not create throwaway scripts for testing.

Keep functions small and modular. Do not create `v2` or `enhanced` versions of existing methods; add new functionality to existing methods.

Add docstrings to public methods but avoid adding code comments.

Don't Repeat Yourself. Refactor code as necessary to avoid duplication of logic.

## Development Commands

Use `uv run` to run commands within the project environment.
Use `uv sync` after updating pyproject.toml to install packages.

Always run `uv run ruff format && uv run ruff check --fix && uv run pyright && uv run pytest` before considering an iteration done.

Target is Python 3.10+.

## Changes and Releasing

Update CHANGELOG.md and docs after each change, if appropriate. Docs are in `docs/` and also `README.md`. Keep changelog entries VERY CONCISE. When making commits (only when specifically requested to do so by the user), always git add each file individual that you know you created or modified; do not use `-A` as that may pick up unrelated files in the working dir. Make your commit messages also VERY CONCISE.

A lot of existing changelog entries are not very concise. Do not match the overly verbose style; the changelog should not be complete user documentation, that's what the docs are for. Keep the change log VERY CONCISE.
