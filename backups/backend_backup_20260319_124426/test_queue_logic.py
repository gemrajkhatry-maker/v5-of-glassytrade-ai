import time
import queue
import logging
import threading

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
log = logging.getLogger("Test")

class MockReasoningService:
    def is_ready(self): return True
    def analyze(self, ctx):
        symbol = ctx.get('symbol', 'unknown')
        log.info(f"Mock reasoning sleeping 2s for {symbol}...")
        time.sleep(2)
        return "Thinking...", "{}"

def mock_worker(q):
    rs = MockReasoningService()
    while True:
        try:
            symbol = q.get()
            log.info(f"Worker picked up {symbol}. Queue size after get is {q.qsize()}")
            ctx = {"symbol": symbol}
            rs.analyze(ctx)
            log.info(f"Worker finished {symbol}. Calling task_done()")
            q.task_done()
        except Exception as e:
            log.error(f"Error {e}")

def run_test():
    log.info("Starting Queue Test...")
    q = queue.Queue()
    
    # Start 1 worker
    threading.Thread(target=mock_worker, args=(q,), daemon=True).start()

    log.info("Queueing 3 symbols immediately (simulating simultaneous candle boundaries)...")
    for sym in ["NIFTY", "BANKNIFTY", "FINNIFTY"]:
        q.put(sym)
        
    log.info(f"Queue size before join: {q.qsize()}")
    log.info("Waiting for queue to drain...")
    q.join()
    log.info("Queue drained. Test complete, all 3 items processed sequentially!")

if __name__ == "__main__":
    run_test()
