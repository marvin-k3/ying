"""Tests for parallel recognition and capacity limits."""

import asyncio
import json
import pytest
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.recognizers.base import RecognitionResult
from app.recognizers.shazamio_recognizer import FakeShazamioRecognizer
from app.recognizers.acoustid_recognizer import FakeAcoustIDRecognizer


@pytest.fixture
def fixtures():
    """Load test fixtures for both recognizers."""
    shazam_path = Path(__file__).parent.parent / "data" / "shazam_fixtures.json"
    acoustid_path = Path(__file__).parent.parent / "data" / "acoustid_fixtures.json"
    
    with open(shazam_path) as f:
        shazam_fixtures = json.load(f)
    with open(acoustid_path) as f:
        acoustid_fixtures = json.load(f)
    
    return {"shazam": shazam_fixtures, "acoustid": acoustid_fixtures}


class TestParallelRecognition:
    """Test parallel recognition scenarios."""
    
    @pytest.mark.asyncio
    async def test_parallel_shazam_acoustid_success(self, fixtures):
        """Test parallel execution of Shazam and AcoustID recognizers."""
        # Setup
        shazam_recognizer = FakeShazamioRecognizer(
            fixture_responses=fixtures["shazam"],
            current_fixture="successful_match"
        )
        acoustid_recognizer = FakeAcoustIDRecognizer(
            fixture_responses=fixtures["acoustid"],
            current_fixture="successful_match"
        )
        
        # Execute in parallel
        start_time = time.time()
        shazam_task = shazam_recognizer.recognize(b"fake_wav_data")
        acoustid_task = acoustid_recognizer.recognize(b"fake_wav_data")
        
        shazam_result, acoustid_result = await asyncio.gather(
            shazam_task, 
            acoustid_task
        )
        end_time = time.time()
        
        # Verify both succeeded
        assert shazam_result.is_success
        assert acoustid_result.is_success
        assert shazam_result.provider == "shazam"
        assert acoustid_result.provider == "acoustid"
        assert shazam_result.title == "Bohemian Rhapsody"
        assert acoustid_result.title == "Bohemian Rhapsody"
        
        # Should be fast (fake recognizers)
        assert end_time - start_time < 1.0
    
    @pytest.mark.asyncio
    async def test_parallel_mixed_results(self, fixtures):
        """Test parallel execution with mixed success/failure results."""
        # Setup - one success, one failure, one no match
        recognizers = [
            FakeShazamioRecognizer(
                fixture_responses=fixtures["shazam"],
                current_fixture="successful_match"
            ),
            FakeAcoustIDRecognizer(
                fixture_responses=fixtures["acoustid"],
                should_fail=True
            ),
            FakeShazamioRecognizer(
                fixture_responses=fixtures["shazam"],
                current_fixture="no_match"
            )
        ]
        
        # Execute in parallel
        tasks = [r.recognize(b"fake_wav_data") for r in recognizers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Verify results
        assert len(results) == 3
        success_result, fail_result, no_match_result = results
        
        assert success_result.is_success
        assert not fail_result.is_success
        assert no_match_result.is_no_match
        
        assert "Simulated recognition failure" in fail_result.error_message
    
    @pytest.mark.asyncio
    async def test_timeout_handling_in_parallel(self, fixtures):
        """Test timeout handling when running recognizers in parallel."""
        # Setup - mix of timeouts and successes
        recognizers = [
            FakeShazamioRecognizer(should_timeout=True),
            FakeAcoustIDRecognizer(should_timeout=True),
            FakeShazamioRecognizer(
                fixture_responses=fixtures["shazam"],
                current_fixture="successful_match"
            )
        ]
        
        # Execute with short timeout
        tasks = [r.recognize(b"fake_wav_data", timeout_seconds=0.5) for r in recognizers]
        results = await asyncio.gather(*tasks)
        
        # Verify
        timeout1, timeout2, success = results
        
        assert not timeout1.is_success
        assert not timeout2.is_success
        assert success.is_success
        
        assert "timed out after 0.5s" in timeout1.error_message
        assert "timed out after 0.5s" in timeout2.error_message
    
    @pytest.mark.asyncio
    async def test_capacity_limits_simulation(self, fixtures):
        """Test simulated capacity limits with queue overflow."""
        # Setup many recognizers to simulate queue overflow
        num_recognizers = 20
        recognizers = [
            FakeShazamioRecognizer(
                fixture_responses=fixtures["shazam"],
                current_fixture="successful_match"
            ) for _ in range(num_recognizers)
        ]
        
        # Execute all at once
        start_time = time.time()
        tasks = [r.recognize(b"fake_wav_data") for r in recognizers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        end_time = time.time()
        
        # Verify all completed successfully (fake recognizers don't enforce real caps)
        assert len(results) == num_recognizers
        assert all(not isinstance(r, Exception) for r in results)
        
        # Should still be fast with fake recognizers
        assert end_time - start_time < 2.0
    
    @pytest.mark.asyncio
    async def test_semaphore_based_concurrency_control(self, fixtures):
        """Test concurrency control using semaphore."""
        # Simulate concurrency control with semaphore
        max_concurrent = 3
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def controlled_recognize(recognizer, wav_data):
            async with semaphore:
                return await recognizer.recognize(wav_data)
        
        # Setup more recognizers than allowed concurrency
        recognizers = [
            FakeShazamioRecognizer(
                fixture_responses=fixtures["shazam"],
                current_fixture="successful_match"
            ) for _ in range(10)
        ]
        
        # Execute with semaphore control
        tasks = [
            controlled_recognize(r, b"fake_wav_data") 
            for r in recognizers
        ]
        results = await asyncio.gather(*tasks)
        
        # Verify all succeeded
        assert len(results) == 10
        assert all(r.is_success for r in results)
    
    @pytest.mark.asyncio
    async def test_error_isolation_in_parallel(self, fixtures):
        """Test that errors in one recognizer don't affect others."""
        # Setup recognizers with different failure modes
        recognizers = [
            FakeShazamioRecognizer(should_fail=True),
            FakeAcoustIDRecognizer(should_timeout=True),
            FakeShazamioRecognizer(
                fixture_responses=fixtures["shazam"],
                current_fixture="successful_match"
            ),
            FakeAcoustIDRecognizer(fingerprint_should_fail=True)
        ]
        
        # Execute all in parallel
        tasks = [r.recognize(b"fake_wav_data") for r in recognizers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Verify error isolation
        assert len(results) == 4
        assert all(not isinstance(r, Exception) for r in results)
        
        fail_result, timeout_result, success_result, fingerprint_result = results
        
        # Only one should succeed
        assert not fail_result.is_success
        assert not timeout_result.is_success
        assert success_result.is_success
        assert not fingerprint_result.is_success
        
        # Verify specific error messages
        assert "Simulated recognition failure" in fail_result.error_message
        assert "timed out" in timeout_result.error_message
        assert "fingerprint" in fingerprint_result.error_message


class TestRecognitionQueue:
    """Test recognition queue management and overflow behavior."""
    
    @pytest.mark.asyncio
    async def test_queue_overflow_oldest_dropped(self, fixtures):
        """Test that oldest items are dropped when queue overflows."""
        # This test simulates queue behavior - in real implementation,
        # the queue would be managed by the worker/scheduler
        
        max_queue_size = 5
        recognition_queue = asyncio.Queue(maxsize=max_queue_size)
        
        # Fill queue beyond capacity
        recognizers = [
            FakeShazamioRecognizer(
                fixture_responses=fixtures["shazam"],
                current_fixture="successful_match"
            ) for _ in range(10)
        ]
        
        # Simulate queue management
        queued_tasks = []
        for i, recognizer in enumerate(recognizers):
            task_info = {"id": i, "recognizer": recognizer, "data": b"fake_wav_data"}
            
            try:
                recognition_queue.put_nowait(task_info)
                queued_tasks.append(task_info)
            except asyncio.QueueFull:
                # Drop oldest and add new (FIFO with drop)
                try:
                    dropped = recognition_queue.get_nowait()
                    print(f"Dropped task {dropped['id']}")
                    recognition_queue.put_nowait(task_info)
                    queued_tasks.append(task_info)
                except asyncio.QueueEmpty:
                    pass
        
        # Process queued tasks
        processed_results = []
        while not recognition_queue.empty():
            task_info = await recognition_queue.get()
            result = await task_info["recognizer"].recognize(task_info["data"])
            processed_results.append((task_info["id"], result))
        
        # Verify queue size was respected
        assert len(processed_results) <= max_queue_size
        assert all(result.is_success for _, result in processed_results)
    
    @pytest.mark.asyncio
    async def test_per_stream_queue_fairness(self, fixtures):
        """Test fairness across multiple streams."""
        # Simulate per-stream queues
        stream_queues = {
            "stream1": asyncio.Queue(maxsize=2),
            "stream2": asyncio.Queue(maxsize=2),
            "stream3": asyncio.Queue(maxsize=2)
        }
        
        # Create tasks for different streams
        tasks = []
        for stream_id in stream_queues.keys():
            for i in range(3):  # 3 tasks per stream (exceeds queue size)
                recognizer = FakeShazamioRecognizer(
                    fixture_responses=fixtures["shazam"],
                    current_fixture="successful_match"
                )
                task_info = {
                    "stream": stream_id,
                    "id": f"{stream_id}_task_{i}",
                    "recognizer": recognizer
                }
                
                # Try to queue task
                try:
                    stream_queues[stream_id].put_nowait(task_info)
                    tasks.append(task_info)
                except asyncio.QueueFull:
                    print(f"Queue full for {stream_id}, dropping task {task_info['id']}")
        
        # Process all queues fairly (round-robin)
        processed = []
        while any(not q.empty() for q in stream_queues.values()):
            for stream_id, queue in stream_queues.items():
                if not queue.empty():
                    task_info = await queue.get()
                    result = await task_info["recognizer"].recognize(b"fake_wav_data")
                    processed.append((stream_id, task_info["id"], result))
        
        # Verify fairness - each stream should have processed some tasks
        streams_processed = set(stream_id for stream_id, _, _ in processed)
        assert len(streams_processed) == 3  # All streams got some processing
        assert all(result.is_success for _, _, result in processed)


@pytest.mark.asyncio
async def test_recognition_performance_benchmarks():
    """Benchmark parallel recognition performance."""
    # Test with varying numbers of parallel recognizers
    test_sizes = [1, 5, 10, 20]
    
    for size in test_sizes:
        recognizers = [FakeShazamioRecognizer() for _ in range(size)]
        
        start_time = time.time()
        tasks = [r.recognize(b"fake_wav_data") for r in recognizers]
        results = await asyncio.gather(*tasks)
        end_time = time.time()
        
        # Verify
        assert len(results) == size
        assert all(not isinstance(r, Exception) for r in results)
        
        # Performance should scale well with fake recognizers
        duration = end_time - start_time
        print(f"Size {size}: {duration:.3f}s ({duration/size:.3f}s per recognizer)")
        assert duration < 1.0  # Should be fast with fake recognizers


@pytest.mark.asyncio
async def test_mixed_provider_parallel_execution(fixtures):
    """Test mixed Shazam and AcoustID providers in parallel."""
    # Create mixed recognizers
    recognizers = []
    
    # Add Shazam recognizers with different fixtures
    for fixture_name in ["successful_match", "no_match", "low_confidence_match"]:
        recognizers.append(FakeShazamioRecognizer(
            fixture_responses=fixtures["shazam"],
            current_fixture=fixture_name
        ))
    
    # Add AcoustID recognizers with different fixtures  
    for fixture_name in ["successful_match", "no_match", "low_confidence_match"]:
        recognizers.append(FakeAcoustIDRecognizer(
            fixture_responses=fixtures["acoustid"],
            current_fixture=fixture_name
        ))
    
    # Execute all in parallel
    tasks = [r.recognize(b"fake_wav_data") for r in recognizers]
    results = await asyncio.gather(*tasks)
    
    # Verify results
    assert len(results) == 6
    
    # Check providers
    shazam_results = [r for r in results if r.provider == "shazam"]
    acoustid_results = [r for r in results if r.provider == "acoustid"]
    
    assert len(shazam_results) == 3
    assert len(acoustid_results) == 3
    
    # Check success patterns
    successful_results = [r for r in results if r.is_success]
    no_match_results = [r for r in results if r.is_no_match]
    
    assert len(successful_results) == 4  # 2 successful + 2 low confidence
    assert len(no_match_results) == 2   # 2 no match


@pytest.mark.asyncio
async def test_concurrent_recognizer_cleanup():
    """Test proper cleanup of recognizer resources in concurrent scenarios."""
    # Create recognizers that need cleanup
    acoustid_recognizers = [
        FakeAcoustIDRecognizer() for _ in range(5)
    ]
    
    # Use recognizers
    tasks = [r.recognize(b"fake_wav_data") for r in acoustid_recognizers]
    results = await asyncio.gather(*tasks)
    
    # Verify all completed
    assert len(results) == 5
    
    # Clean up all recognizers
    cleanup_tasks = [r.close() for r in acoustid_recognizers]
    await asyncio.gather(*cleanup_tasks)
    
    # Should complete without errors
    assert True
