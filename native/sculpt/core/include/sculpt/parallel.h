// Sculpting engine — parallel_for on a persistent worker pool. std::thread based, so it
// works the same with MSVC, Apple Clang (no OpenMP) and GCC.
//
// A brush dab runs several parallel loops; creating and joining threads per
// loop cost ~20-50 us per thread (x cores x loops per dab), so the workers are
// created once and parked on a condition variable. Small ranges run inline.
// Nested calls (a parallelFor inside a worker) run inline too.
#pragma once
#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <functional>
#include <mutex>
#include <thread>
#include <vector>

namespace sculpt {

class ThreadPool {
public:
    static ThreadPool& get() {
        std::lock_guard<std::mutex> l(instanceMutex());
        if (!instance()) instance() = new ThreadPool;
        return *instance();
    }
    // Join the workers (the host uninitializePlugin). Never left to a static
    // destructor: on Windows that runs under the DLL loader lock and joining
    // threads there deadlocks. The next get() starts a fresh pool.
    static void shutdown() {
        std::lock_guard<std::mutex> l(instanceMutex());
        delete instance();
        instance() = nullptr;
    }
    unsigned size() const { return (unsigned)workers_.size() + 1; }  // + the calling thread
    static bool inWorker() { return tlsWorker(); }

    // Runs job(chunk) for chunk in [0, chunks) across the pool + caller; blocks.
    void run(int chunks, const std::function<void(int)>& job) {
        std::unique_lock<std::mutex> callLock(callMutex_);  // one parallel region at a time
        unsigned long long gen;
        {
            std::lock_guard<std::mutex> l(m_);
            job_ = &job;
            chunks_ = chunks;
            pending_ = chunks;
            gen = ++generation_;
            // generation in the high bits: a worker still finishing an older run
            // can never claim (or skip) a chunk of this one - claims are CAS'd
            next_.store(gen << 32);
        }
        cv_.notify_all();
        work(gen);
        std::unique_lock<std::mutex> l(m_);
        done_.wait(l, [&] { return pending_ == 0; });
    }

private:
    ThreadPool() {
        unsigned hw = std::max(1u, std::thread::hardware_concurrency());
        for (unsigned i = 1; i < hw; ++i) workers_.emplace_back([this] { loop(); });
    }
    ~ThreadPool() {
        {
            std::lock_guard<std::mutex> l(m_);
            stop_ = true;
        }
        cv_.notify_all();
        for (auto& t : workers_) t.join();
    }
    static ThreadPool*& instance() {
        static ThreadPool* p = nullptr;
        return p;
    }
    static std::mutex& instanceMutex() {
        static std::mutex m;
        return m;
    }
    static bool& tlsWorker() {
        static thread_local bool w = false;
        return w;
    }
    void work(unsigned long long gen) {
        int done = 0;
        for (;;) {
            unsigned long long v = next_.load();
            if ((v >> 32) != gen) break;
            int idx = (int)(v & 0xffffffffu);
            if (idx >= chunks_.load()) break;  // written before next_ was published
            if (!next_.compare_exchange_weak(v, v + 1)) continue;
            (*job_)(idx);
            ++done;
        }
        if (done) {
            std::lock_guard<std::mutex> l(m_);
            pending_ -= done;
            if (pending_ == 0) done_.notify_all();
        }
    }
    void loop() {
        tlsWorker() = true;
        unsigned long long seen = 0;
        for (;;) {
            {
                std::unique_lock<std::mutex> l(m_);
                cv_.wait(l, [&] { return stop_ || generation_ != seen; });
                if (stop_) return;
                seen = generation_;
            }
            work(seen);
        }
    }
    std::vector<std::thread> workers_;
    std::mutex m_, callMutex_;
    std::condition_variable cv_, done_;
    const std::function<void(int)>* job_ = nullptr;   // valid while its generation runs
    std::atomic<unsigned long long> next_{0};          // (generation << 32) | next chunk
    std::atomic<int> chunks_{0};
    int pending_ = 0;
    unsigned long long generation_ = 0;
    bool stop_ = false;
};

template <class F>
void parallelFor(int n, F&& fn, int grain = 4096) {
    ThreadPool& pool = ThreadPool::get();
    if (n < grain * 2 || pool.size() == 1 || ThreadPool::inWorker()) {
        for (int i = 0; i < n; ++i) fn(i);
        return;
    }
    int chunks = std::min<int>((int)pool.size() * 4, n / grain);
    int step = (n + chunks - 1) / chunks;
    std::function<void(int)> job = [&](int c) {
        int lo = c * step, hi = std::min(n, lo + step);
        for (int i = lo; i < hi; ++i) fn(i);
    };
    pool.run(chunks, job);
}

}  // namespace sculpt
