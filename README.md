# Meerkat

Python library for monitoring data sources and tracking changes over time.
Just as meerkats in nature keep vigilant watch over their surroundings, this library helps you maintain awareness of changes in your data sources.

## Installation

Using `pip`:

```sh
pip install git+https://github.com/niqodea/meerkat.git@v0.1.0
```

## Core Concepts

### Meerkat

A meerkat (`Meerkat`) is the main orchestrator that monitors a truth source for changes. It periodically:
1. Fetches data from the truth source
2. Tracks changes by comparing against the previous state
3. Executes actions in response to detected changes

### Truth Source & Fetchers

A truth source is any data source you want to monitor. The library is flexible and can work with any data source that can be represented as a dictionary of items with unique IDs.

Truth source fetchers (`TruthSourceFetcher`) are responsible for:
* Fetching data from the truth source
* Converting the data into a dictionary of `Thing` objects (items that can be monitored)
* Handling any errors that occur during fetching

### Snapshot Manager

The snapshot manager (`SnapshotManager`) is responsible for:
* Tracking the current state of monitored items
* Detecting changes by comparing against the previous state
* Computing operations (Create, Update, Delete) based on the differences

The base implementation (`BaseSnapshotManager`) stores snapshots as JSON files on disk, making it easy to inspect the state with a text editor.

### Action Executor

Action executors (`ActionExecutor`) define what happens when changes are detected. They receive a dictionary of operations (Create/Update/Delete) and can perform any desired actions in response.

The base implementation (`BaseActionExecutor`) logs changes as text.

## CLI Module

The CLI module provides a convenient way to deploy meerkats that report changes to the terminal.
One of its main advantages is simplicity, as you only need to provide the following to get started:
* A truth source fetcher to get your data
* A stringifier function to convert your items to human-readable text

The module automatically handles everything else with sensible defaults:
* Colored terminal output
* File-based state management
* Error logging
* Terminal controls

### Terminal Controls

* `CTRL+L`: Clear the screen (useful after reading updates)
* `CTRL+D`: Graceful shutdown

### Usage Example

```python
from meerkat.cli import CliDeployer

specs = {
    "domain-name": CliDeployer.MeerkatSpec(
        truth_source_fetcher=your_fetcher,
        stringifier=lambda x: str(x),  # How to convert things to strings
        snapshot_path=Path("./snapshots"),  # Where to store state
        interval_seconds=60  # How often to check for changes
    )
}

deployer = await CliDeployer.create(specs)
await deployer.run()
```

## License

Licensed under the MIT License. Check the [LICENSE](./LICENSE.md) file for details.
