"""External data-provider adapters.

Each sub-package exposes a provider-agnostic interface plus one or more
concrete adapters. The rest of the app (services, API, UI) depends only on
the interface, so swapping providers never touches business logic.
"""
