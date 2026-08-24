from dataclasses import dataclass


@dataclass
class RetryPolicy:
    max_retries: int = 2

    def should_retry(self, attempts: int) -> bool:
        return attempts < self.max_retries
