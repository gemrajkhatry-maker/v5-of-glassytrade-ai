class TickSequencer:  
    def __init__(self):  
        self.sequence = 0  
        self.duplicate_buffer = set()  

    def next(self):  
        self.sequence += 1  
        return self.sequence  

    def check_duplicate(self, seq):  
        if seq in self.duplicate_buffer:  
            return True  
        self.duplicate_buffer.add(seq)  
        return False  

    def clear_duplicates(self):  
        self.duplicate_buffer.clear()