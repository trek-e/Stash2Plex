# worker Module

Background job processing with retry logic and circuit breaker protection.

**Architecture:** See [Processing Layer](../ARCHITECTURE.md#worker-processing-layer) for design rationale.

## QueueProcessor

::: worker.processor
    options:
      members_order: source
      show_source: true

## Circuit Breaker

::: worker.circuit_breaker
    options:
      members_order: source
      show_source: true

## Backoff Calculator

::: worker.backoff
    options:
      members_order: source
      show_source: true
