# Job Monitor

This example project demonstrates how to use the Meerkat library to monitor job postings from various sources.

## Overview

The main components are:

* **Fetchers**: Retrieve job postings from different data sources. The default fetchers are not implemented - it's up to the user to provide their own implementation. If you need assistance with this, feel free to reach out.
* **Job Model**: Represents a job posting with title, location, and URL.
* **Job Stringifier**: Converts job postings to human-readable strings with highlighting.
* **Main Application**: Sets up the Meerkat deployment to monitor the job data sources.

## Usage

Set up the project with

```sh
make install
```

Run the meerkats with

```sh
make run
```

The terminal will display job postings and changes over time.

## Customization

You can add more fetchers, modify the job model, and adjust the monitoring configuration to fit your needs.
