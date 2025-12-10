# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Mouc** is a YAML-based dependency tracker and automatic scheduler for project roadmaps. It takes a YAML file describing work items and their dependencies, and produces scheduled Gantt charts, dependency graphs, and documentation.

**Core Purpose**: Define *what* needs to happen and dependencies; Mouc computes *when* things should happen. Not a full project management system.

## Architecture

The system is built around YAML data files with configurable entity types. By default, three types are provided (capabilities, user stories, outcomes), but users can define custom types in `mouc_config.yaml`.

Key features:
- **Automatic scheduling** from dependencies, deadlines, priorities, and resource constraints
- **Workflows** that expand entities into multiple phases (design → implement → review)
- **Resource management** with availability tracking and auto-assignment
- **Jira integration** for syncing metadata
- **Multiple outputs**: Mermaid Gantt charts, Graphviz graphs, Markdown/DOCX docs

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
