class TickNormalizer:  
    def __init__(self, exchange: str = "NSE"):  
        self.exchange = exchange  
        self.conversion_cache = {}      def normalize(self, tick):  
        """Convert exchange-specific tick to canonical format."""  
        canonical = {  
            "timestamp": tick.timestamp,  
            "symbol": tick.symbol,  
            "price": tick.price,  
            "volume": tick.volume,  
            "bid": tick.bid,  
            "ask": tick.ask,  
            "exchange": self.exchange  
        }  
        # Cache conversion factors per symbol  
        key = (self.exchange, tick.symbol)  
        if key not in self.conversion_cache:  
            self.conversion_cache[key] = self._init_conversion_factors()  
        canonical["conversion_cache"] = self.conversion_cache[key]  
        return canonical  

    def _init_conversion_factors(self):  
        """Initialize symbol-specific conversion factors."""  
        # Placeholder for exchange-specific logic  
        return {  
            "tick_size": 0.05,  
            "lot_size": 1,  
            "min_volume": 1  
        }