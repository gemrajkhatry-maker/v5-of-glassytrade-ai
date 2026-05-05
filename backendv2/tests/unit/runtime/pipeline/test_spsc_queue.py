"""Tests for SPSCQueue — lock-free ring buffer, push/pop/drain/clear."""

from app.runtime.pipeline import SPSCQueue


def test_empty_queue():
    q = SPSCQueue[int](capacity=4)
    assert q.empty
    assert not q.full
    assert q.size == 0
    assert q.pop() is None


def test_push_and_pop():
    q = SPSCQueue[int](capacity=4)
    assert q.push(1)
    assert q.push(2)
    assert not q.empty
    assert q.size == 2
    assert q.pop() == 1
    assert q.pop() == 2
    assert q.empty


def test_queue_full():
    q = SPSCQueue[int](capacity=2)
    assert q.push(1)
    assert q.push(2)
    assert q.full
    assert not q.push(3)
    assert q.size == 2


def test_wrap_around():
    q = SPSCQueue[int](capacity=3)
    q.push(1)
    q.push(2)
    q.push(3)
    assert q.full
    assert q.pop() == 1
    assert not q.full
    assert q.push(4)
    assert q.pop() == 2
    assert q.pop() == 3
    assert q.pop() == 4
    assert q.empty


def test_drain():
    q = SPSCQueue[int](capacity=10)
    q.push(1)
    q.push(2)
    q.push(3)
    items = q.drain()
    assert items == [1, 2, 3]
    assert q.empty


def test_clear():
    q = SPSCQueue[int](capacity=4)
    q.push(1)
    q.push(2)
    q.clear()
    assert q.empty
    assert q.size == 0
    assert q.pop() is None