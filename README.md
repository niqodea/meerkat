# Meerkat

Python library for monitoring data sources and tracking changes over time.
Just as meerkats in nature keep vigilant watch over their surroundings, this library helps you maintain awareness of changes in your data sources.

## Installation

Using `pip`:

```sh
pip install git+https://github.com/niqodea/meerkat.git@v0.1.0
```

## Core Concepts

### Thing

`Thing` is the base dataclass that you can extend to represent items you want to monitor.
For example, if you're monitoring academic papers, you might create a `Paper` class that extends `Thing` with fields like `title`, `authors`, and `citations`.
Each `Thing` must have a unique identifier that allows the system to track it over time.

### Data source

A data source is any collection of `Thing` objects you want to monitor.
The library is flexible and can work with any data source that can be represented as a dictionary of these uniquely identified items.

### Meerkat

A meerkat (`Meerkat`) is the main orchestrator that monitors a data source for changes. It periodically:
1. Fetches data from the data source
2. Tracks changes by comparing against the previous state
3. Executes actions in response to detected changes

### Fetcher

A fetcher (`Fetcher`) is responsible for:

* Fetching data from the data source
* Converting the data into a dictionary of `Thing` objects (items that can be monitored)
* Communicating errors that occur during fetching

### Snapshot Manager

A snapshot manager (`SnapshotManager`) is responsible for:
* Tracking the current state of monitored items
* Detecting changes by comparing against the previous state
* Computing operations (Create, Update, Delete) based on the differences

The standard implementation (`JsonSnapshotManager`) stores snapshots as JSON files on disk, making it easy to inspect the state with a text editor.

### Action Executor

An action executor (`ActionExecutor`) defines what happens when changes are detected.
It receives a dictionary of operations (Create/Update/Delete) and can perform any desired actions in response.

## CLI Module

The CLI module provides a convenient way to deploy meerkats that report changes to the terminal.
One of its main advantages is simplicity, as you only need to implement the following to get started:
* A fetcher to get your data
* A stringifier function to convert your items to human-readable text

The module automatically handles everything else with sensible defaults.

### Terminal Controls

* `CTRL+L`: Clear the screen (useful after reading updates)
* `CTRL+D`: Graceful shutdown

### Usage Example

```python
from meerkat.cli import CliDeployer

specs = {
    "domain-name": CliDeployer.MeerkatSpec(
        fetcher=your_fetcher,
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
