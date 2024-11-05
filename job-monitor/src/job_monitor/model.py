from __future__ import annotations

import re
from dataclasses import dataclass

from meerkat import Thing
from meerkat.cli import Stringifier


@dataclass
class Job(Thing):
    title: str

    location: str | None = None
    url: str | None = None


class JobStringifier(Stringifier[Job]):
    def __init__(self, highlight_pattern: str) -> None:
        self._highlight_pattern = highlight_pattern

    def run(self, job: Job) -> str:
        job_string = ""

        if re.search(self._highlight_pattern, job.title.lower()):
            job_string += f"{self.RED}"
            job_string += "! "
            job_string += f"{self.RESET}"
        else:
            job_string += "  "

        job_string += f"Title: '{job.title}'"

        if job.location is not None:
            job_string += f", Location: '{job.location}'"

        if job.url is not None:
            job_string += f", URL: {job.url}"

        return job_string

    @staticmethod
    def create(highlight_terms: list[str]) -> JobStringifier:
        pattern = rf"\b(?:{'|'.join(highlight_terms)})\b"
        return JobStringifier(pattern)

    RED = "\033[31m"
    RESET = "\033[0m"
