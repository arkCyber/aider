"""
Unit tests for rate limiter module.
"""

import time
import unittest

from aider.rate_limiter import (
    RateLimitInfo,
    RateLimitPolicy,
    RateLimiter,
    SlidingWindowRateLimiter,
    TokenBucket,
    check_rate_limit,
    get_rate_limiter,
)


class TestTokenBucket(unittest.TestCase):
    """Test the token bucket implementation."""

    def test_token_bucket_initialization(self):
        """Test token bucket initialization."""
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        
        self.assertEqual(bucket.capacity, 10)
        self.assertEqual(bucket.refill_rate, 1.0)
    
    def test_consume_tokens(self):
        """Test consuming tokens."""
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        
        result = bucket.consume(5)
        self.assertTrue(result)
        
        result = bucket.consume(6)  # Should fail (only 5 tokens left)
        self.assertFalse(result)
    
    def test_get_available_tokens(self):
        """Test getting available tokens."""
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        
        available = bucket.get_available_tokens()
        self.assertEqual(available, 10)
        
        bucket.consume(5)
        available = bucket.get_available_tokens()
        self.assertEqual(available, 5)
    
    def test_token_refill(self):
        """Test token refill over time."""
        bucket = TokenBucket(capacity=10, refill_rate=10.0)  # 10 tokens per second
        
        bucket.consume(10)
        self.assertEqual(bucket.get_available_tokens(), 0)
        
        time.sleep(0.2)  # Wait for 2 tokens to refill
        available = bucket.get_available_tokens()
        self.assertGreater(available, 0)


class TestRateLimitInfo(unittest.TestCase):
    """Test rate limit info dataclass."""

    def test_rate_limit_info_creation(self):
        """Test creating rate limit info."""
        info = RateLimitInfo(
            is_limited=False,
            remaining_requests=10,
            reset_time=None,
            retry_after=0.0,
        )
        
        self.assertFalse(info.is_limited)
        self.assertEqual(info.remaining_requests, 10)


class TestRateLimiter(unittest.TestCase):
    """Test the rate limiter."""

    def setUp(self):
        """Set up test fixtures."""
        self.policy = RateLimitPolicy(
            requests_per_minute=60,
            requests_per_hour=1000,
            requests_per_day=10000,
        )
        self.limiter = RateLimiter(self.policy)
    
    def test_is_allowed(self):
        """Test checking if request is allowed."""
        info = self.limiter.is_allowed("test_user")
        
        self.assertFalse(info.is_limited)
        self.assertGreater(info.remaining_requests, 0)
    
    def test_rate_limit_enforcement(self):
        """Test that rate limit is enforced."""
        # Use a very restrictive policy for testing
        policy = RateLimitPolicy(requests_per_minute=2)
        limiter = RateLimiter(policy)
        
        # Should allow first 2 requests
        info1 = limiter.is_allowed("test_user")
        info2 = limiter.is_allowed("test_user")
        
        self.assertFalse(info1.is_limited)
        self.assertFalse(info2.is_limited)
        
        # Third request should be limited
        info3 = limiter.is_allowed("test_user")
        self.assertTrue(info3.is_limited)
    
    def test_get_status(self):
        """Test getting rate limit status."""
        status = self.limiter.get_status("test_user")
        
        self.assertIn("minute", status)
        self.assertIn("hour", status)
        self.assertIn("day", status)
    
    def test_reset(self):
        """Test resetting rate limit."""
        self.limiter.is_allowed("test_user")
        self.limiter.reset("test_user")
        
        # After reset, should be able to make requests again
        info = self.limiter.is_allowed("test_user")
        self.assertFalse(info.is_limited)
    
    def test_update_policy(self):
        """Test updating rate limit policy."""
        new_policy = RateLimitPolicy(requests_per_minute=10)
        self.limiter.update_policy(new_policy)
        
        self.assertEqual(self.limiter.policy.requests_per_minute, 10)


class TestSlidingWindowRateLimiter(unittest.TestCase):
    """Test the sliding window rate limiter."""

    def setUp(self):
        """Set up test fixtures."""
        self.limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=10)
    
    def test_is_allowed(self):
        """Test checking if request is allowed."""
        result = self.limiter.is_allowed()
        self.assertTrue(result)
    
    def test_window_enforcement(self):
        """Test that window limit is enforced."""
        # Should allow 5 requests
        for _ in range(5):
            self.assertTrue(self.limiter.is_allowed())
        
        # 6th request should be denied
        self.assertFalse(self.limiter.is_allowed())
    
    def test_window_sliding(self):
        """Test that window slides over time."""
        # Fill the window
        for _ in range(5):
            self.assertTrue(self.limiter.is_allowed())
        
        # Should be limited
        self.assertFalse(self.limiter.is_allowed())
        
        # Wait for window to slide
        time.sleep(11)
        
        # Should be allowed again
        self.assertTrue(self.limiter.is_allowed())
    
    def test_get_wait_time(self):
        """Test getting wait time."""
        wait_time = self.limiter.get_wait_time()
        self.assertGreaterEqual(wait_time, 0.0)


class TestGlobalRateLimiter(unittest.TestCase):
    """Test global rate limiter instance."""

    def test_get_rate_limiter(self):
        """Test getting global rate limiter."""
        limiter = get_rate_limiter()
        self.assertIsNotNone(limiter)
        
        # Should return same instance
        limiter2 = get_rate_limiter()
        self.assertIs(limiter, limiter2)
    
    def test_check_rate_limit(self):
        """Test convenience function for rate limit checking."""
        is_allowed, retry_after = check_rate_limit("test_user")
        
        self.assertIsInstance(is_allowed, bool)
        self.assertIsInstance(retry_after, float)


if __name__ == "__main__":
    unittest.main()
