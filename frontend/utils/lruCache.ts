/**
 * LRU (Least Recently Used) Cache
 * 
 * Efficient cache with maximum size limit.
 * Automatically removes least recently used items when capacity is reached.
 * 
 * Use case: Price lines cache, chart data cache, etc.
 */
export class LRUCache<K, V> {
    private cache: Map<K, V>;
    private readonly capacity: number;

    constructor(capacity: number = 100) {
        this.cache = new Map<K, V>();
        this.capacity = capacity;
    }

    /**
     * Get item from cache
     * Returns undefined if not found
     */
    get(key: K): V | undefined {
        const item = this.cache.get(key);
        
        if (item !== undefined) {
            // Move to end (most recently used)
            this.cache.delete(key);
            this.cache.set(key, item);
        }
        
        return item;
    }

    /**
     * Set item in cache
     * Removes least recently used item if at capacity
     */
    set(key: K, value: V): void {
        // If key exists, delete it first (to update position)
        if (this.cache.has(key)) {
            this.cache.delete(key);
        }
        
        // If at capacity, remove least recently used (first item)
        if (this.cache.size >= this.capacity) {
            const firstKey = this.cache.keys().next().value;
            if (firstKey !== undefined) {
                this.cache.delete(firstKey);
            }
        }
        
        // Add new item (most recently used)
        this.cache.set(key, value);
    }

    /**
     * Check if key exists in cache
     */
    has(key: K): boolean {
        return this.cache.has(key);
    }

    /**
     * Delete item from cache
     */
    delete(key: K): boolean {
        return this.cache.delete(key);
    }

    /**
     * Clear all items
     */
    clear(): void {
        this.cache.clear();
    }

    /**
     * Get cache size
     */
    get size(): number {
        return this.cache.size;
    }

    /**
     * Get all keys (in order of least to most recently used)
     */
    keys(): K[] {
        return Array.from(this.cache.keys());
    }

    /**
     * Get all values (in order of least to most recently used)
     */
    values(): V[] {
        return Array.from(this.cache.values());
    }

    /**
     * Convert to array of entries
     */
    entries(): [K, V][] {
        return Array.from(this.cache.entries());
    }
}

/**
 * Create a memoized function with LRU caching
 * 
 * @param fn Function to memoize
 * @param keyFn Function to generate cache key from arguments
 * @param capacity Maximum cache size (default: 100)
 */
export function memoizeWithLRU<A extends unknown[], R>(
    fn: (...args: A) => R,
    keyFn: (...args: A) => string = (...args) => JSON.stringify(args),
    capacity: number = 100
): (...args: A) => R {
    const cache = new LRUCache<string, R>(capacity);

    return (...args: A): R => {
        const key = keyFn(...args);
        
        const cached = cache.get(key);
        if (cached !== undefined) {
            return cached;
        }
        
        const result = fn(...args);
        cache.set(key, result);
        return result;
    };
}
