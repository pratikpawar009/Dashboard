# Performance baseline

- No N+1 queries or unbounded fan-out reads. Batch or paginate.
- Pagination on every list endpoint (default page size, max page size).
- Every retry has bounded attempts and exponential backoff with jitter.
- I/O has explicit timeouts. No silent infinite waits.
- Don't optimise without a measurement. Profile, then change.
- Cache invalidation is explicit. Document TTL and the invalidating event.
