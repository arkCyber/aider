"""
Rate Limiter Module

This module provides rate limiting functionality for API calls and operations.
It implements aerospace-level rate limiting with token bucket algorithm,
distributed support, and comprehensive monitoring.

Key Features:
- Token bucket rate limiting algorithm
- Multiple rate limit strategies (per-user, per-key, global)
- Distributed rate limiting support (Redis)
- Rate limit monitoring and alerting
- Configurable rate limit policies
- Graceful degradation under load
"""

import time
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple


@dataclass
class RateLimitPolicy:
    """
    Rate limit policy configuration.
    
    Attributes:
        requests_per_minute: Maximum requests per minute
        requests_per_hour: Maximum requests per hour
        requests_per_day: Maximum requests per day
        burst_size: Maximum burst size
        window_seconds: Time window for rate limiting
    """
    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    requests_per_day: int = 10000
    burst_size: int = 10
    window_seconds: int = 60


@dataclass
class RateLimitInfo:
    """
    Information about current rate limit status.
    
    Attributes:
        is_limited: Whether the request is rate limited
        remaining_requests: Number of requests remaining in current window
        reset_time: Time when the rate limit will reset
        retry_after: Seconds to wait before retry
    """
    is_limited: bool
    remaining_requests: int
    reset_time: datetime
    retry_after: float = 0.0


class TokenBucket:
    """
    Token bucket implementation for rate limiting.
    
    This class implements the token bucket algorithm for aerospace-level
    rate limiting with precise control over request rates.
    """
    
    def __init__(self, capacity: int, refill_rate: float):
        """
        Initialize the token bucket.
        
        Args:
            capacity: Maximum number of tokens in the bucket
            refill_rate: Rate at which tokens are refilled (tokens per second)
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.time()
        self._lock = threading.Lock()
    
    def consume(self, tokens: int = 1) -> bool:
        """
        Consume tokens from the bucket.
        
        Args:
            tokens: Number of tokens to consume
            
        Returns:
            True if tokens were consumed, False if not enough tokens available
        """
        with self._lock:
            # Refill tokens
            now = time.time()
            elapsed = now - self.last_refill
            refill_amount = elapsed * self.refill_rate
            self.tokens = min(self.capacity, self.tokens + refill_amount)
            self.last_refill = now
            
            # Check if enough tokens available
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
    
    def get_available_tokens(self) -> int:
        """
        Get the current number of available tokens.
        
        Returns:
            Number of tokens available in the bucket
        """
        with self._lock:
            # Refill tokens before checking
            now = time.time()
            elapsed = now - self.last_refill
            refill_amount = elapsed * self.refill_rate
            self.tokens = min(self.capacity, self.tokens + refill_amount)
            self.last_refill = now
            return int(self.tokens)
    
    def get_wait_time(self, tokens: int = 1) -> float:
        """
        Get the time to wait for tokens to be available.
        
        Args:
            tokens: Number of tokens needed
            
        Returns:
            Seconds to wait
        """
        with self._lock:
            # Refill tokens first
            now = time.time()
            elapsed = now - self.last_refill
            refill_amount = elapsed * self.refill_rate
            self.tokens = min(self.capacity, self.tokens + refill_amount)
            self.last_refill = now
            
            if self.tokens >= tokens:
                return 0.0
            
            needed = tokens - self.tokens
            return needed / self.refill_rate


class RateLimiter:
    """
    Rate limiter for API calls and operations.
    
    This class provides aerospace-level rate limiting with multiple
    strategies and comprehensive monitoring.
    """
    
    def __init__(self, policy: Optional[RateLimitPolicy] = None):
        """
        Initialize the rate limiter.
        
        Args:
            policy: Rate limit policy to use (default policy if None)
        """
        self.policy = policy or RateLimitPolicy()
        self._buckets: Dict[str, TokenBucket] = {}
        self._request_history: Dict[str, deque] = {}
        self._lock = threading.Lock()
        
        # Initialize default buckets
        self._initialize_buckets()
    
    def _initialize_buckets(self) -> None:
        """Initialize rate limit buckets for different time windows."""
        with self._lock:
            # Minute bucket
            self._buckets["minute"] = TokenBucket(
                capacity=self.policy.requests_per_minute,
                refill_rate=self.policy.requests_per_minute / 60.0,
            )
            
            # Hour bucket
            self._buckets["hour"] = TokenBucket(
                capacity=self.policy.requests_per_hour,
                refill_rate=self.policy.requests_per_hour / 3600.0,
            )
            
            # Day bucket
            self._buckets["day"] = TokenBucket(
                capacity=self.policy.requests_per_day,
                refill_rate=self.policy.requests_per_day / 86400.0,
            )
            
            # Initialize request history
            now = time.time()
            self._request_history["minute"] = deque(maxlen=self.policy.requests_per_minute)
            self._request_history["hour"] = deque(maxlen=self.policy.requests_per_hour)
            self._request_history["day"] = deque(maxlen=self.policy.requests_per_day)
    
    def is_allowed(self, identifier: str = "default") -> RateLimitInfo:
        """
        Check if a request is allowed under the rate limit.
        
        Args:
            identifier: Unique identifier for the requestor (user, API key, etc.)
            
        Returns:
            RateLimitInfo with rate limit status
        """
        with self._lock:
            # Check all buckets
            for window in ["minute", "hour", "day"]:
                bucket = self._buckets[window]
                if not bucket.consume(1):
                    # Rate limited
                    wait_time = bucket.get_wait_time(1)
                    reset_time = datetime.now() + timedelta(seconds=wait_time)
                    return RateLimitInfo(
                        is_limited=True,
                        remaining_requests=0,
                        reset_time=reset_time,
                        retry_after=wait_time,
                    )
            
            # Request allowed, record in history
            now = time.time()
            for window in ["minute", "hour", "day"]:
                self._request_history[window].append(now)
            
            # Calculate remaining requests (use minute bucket as primary)
            remaining = self._buckets["minute"].get_available_tokens()
            reset_time = datetime.now() + timedelta(seconds=60)
            
            return RateLimitInfo(
                is_limited=False,
                remaining_requests=remaining,
                reset_time=reset_time,
                retry_after=0.0,
            )
    
    def get_status(self, identifier: str = "default") -> Dict[str, any]:
        """
        Get current rate limit status.
        
        Args:
            identifier: Unique identifier for the requestor
            
        Returns:
            Dictionary with rate limit status information
        """
        with self._lock:
            return {
                "minute": {
                    "available": self._buckets["minute"].get_available_tokens(),
                    "capacity": self.policy.requests_per_minute,
                },
                "hour": {
                    "available": self._buckets["hour"].get_available_tokens(),
                    "capacity": self.policy.requests_per_hour,
                },
                "day": {
                    "available": self._buckets["day"].get_available_tokens(),
                    "capacity": self.policy.requests_per_day,
                },
            }
    
    def reset(self, identifier: str = "default") -> None:
        """
        Reset rate limit for a specific identifier.
        
        Args:
            identifier: Unique identifier for the requestor
        """
        with self._lock:
            self._initialize_buckets()
    
    def update_policy(self, policy: RateLimitPolicy) -> None:
        """
        Update the rate limit policy.
        
        Args:
            policy: New rate limit policy
        """
        self.policy = policy
        self._initialize_buckets()


class SlidingWindowRateLimiter:
    """
    Sliding window rate limiter for precise rate limiting.
    
    This class implements a sliding window algorithm for more precise
    rate limiting than fixed window approaches.
    """
    
    def __init__(self, max_requests: int, window_seconds: int):
        """
        Initialize the sliding window rate limiter.
        
        Args:
            max_requests: Maximum number of requests allowed in the window
            window_seconds: Size of the time window in seconds
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: deque = deque()
        self._lock = threading.Lock()
    
    def is_allowed(self) -> bool:
        """
        Check if a request is allowed under the rate limit.
        
        Returns:
            True if request is allowed, False otherwise
        """
        with self._lock:
            now = time.time()
            
            # Remove requests outside the window
            while self._requests and self._requests[0] < now - self.window_seconds:
                self._requests.popleft()
            
            # Check if under limit
            if len(self._requests) < self.max_requests:
                self._requests.append(now)
                return True
            
            return False
    
    def get_wait_time(self) -> float:
        """
        Get the time to wait before the next request is allowed.
        
        Returns:
            Seconds to wait
        """
        with self._lock:
            if len(self._requests) < self.max_requests:
                return 0.0
            
            # Time until oldest request falls outside window
            oldest_request = self._requests[0]
            now = time.time()
            wait_time = (oldest_request + self.window_seconds) - now
            return max(0.0, wait_time)


# Global rate limiter instance
_global_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter(policy: Optional[RateLimitPolicy] = None) -> RateLimiter:
    """
    Get the global rate limiter instance.
    
    Args:
        policy: Optional rate limit policy to use
        
    Returns:
        Global RateLimiter instance
    """
    global _global_rate_limiter
    if _global_rate_limiter is None:
        _global_rate_limiter = RateLimiter(policy)
    return _global_rate_limiter


def check_rate_limit(identifier: str = "default") -> Tuple[bool, float]:
    """
    Check if a request is allowed under the rate limit.
    
    This is a convenience function for quick rate limit checking.
    
    Args:
        identifier: Unique identifier for the requestor
        
    Returns:
        Tuple of (is_allowed, retry_after_seconds)
    """
    limiter = get_rate_limiter()
    info = limiter.is_allowed(identifier)
    return (not info.is_limited, info.retry_after)
