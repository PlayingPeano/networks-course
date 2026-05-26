import random
import threading
import queue
import json
import argparse
import sys
from typing import Dict, List, Tuple, Set

TableEntry = Tuple[str, int]

class Router(threading.Thread):
    def __init__(self, ip: str,
                 barrier_send: threading.Barrier,
                 barrier_recv: threading.Barrier,
                 step_done: threading.Barrier,
                 stop_event: threading.Event,
                 verbose: bool):
        super().__init__(daemon=True)
        self.ip = ip
        self.neighbors: List['Router'] = []        
        self.table: Dict[str, TableEntry] = {}     
        self.in_queue = queue.Queue()
        self.barrier_send = barrier_send
        self.barrier_recv = barrier_recv
        self.step_done = step_done
        self.stop_event = stop_event
        self.verbose = verbose
        self.step = 0

    def set_neighbors(self, neighbors: List['Router']):
        self.neighbors = neighbors
        self.table.clear()
        for nb in neighbors:
            self.table[nb.ip] = (nb.ip, 1)

    def run(self):
        while not self.stop_event.is_set():
            self.step += 1

            for nb in self.neighbors:
                to_send = {}
                for dest, (nh, metric) in self.table.items():
                    if nh != nb.ip:
                        to_send[dest] = (nh, metric)
                nb.in_queue.put((self.ip, to_send))

            self.barrier_send.wait()

            updated = False
            while True:
                try:
                    sender_ip, received_table = self.in_queue.get_nowait()
                except queue.Empty:
                    break

                for dest, (_, adv_metric) in received_table.items():
                    if dest == self.ip:
                        continue
                    new_metric = adv_metric + 1
                    if new_metric > 16:   
                        continue

                    if dest not in self.table:
                        self.table[dest] = (sender_ip, new_metric)
                        updated = True
                    else:
                        cur_nh, cur_metric = self.table[dest]
                        if new_metric < cur_metric or cur_nh == sender_ip:
                            if new_metric != cur_metric or cur_nh != sender_ip:
                                self.table[dest] = (sender_ip, new_metric)
                                updated = True

            self.barrier_recv.wait()   

            if self.verbose:
                self.print_table(step=self.step)

            self.step_done.wait()
    def print_table(self, step: int = None):
        if step is not None:
            print(f"Simulation step {step} of router {self.ip}")
        else:
            print(f"Final state of router {self.ip} table:")
        header = f"{'[Source IP]':<18} {'[Destination IP]':<20} {'[Next Hop]':<18} {'[Metric]':<8}"
        print(header)
        for dest, (nh, metric) in sorted(self.table.items()):
            print(f"{self.ip:<18} {dest:<20} {nh:<18} {metric:<8}")
        print()

def generate_random_topology(num_routers: int, link_prob: float = 0.3) -> Dict[str, Set[str]]:
    ips = []
    for _ in range(num_routers):
        while True:
            ip = f"10.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"
            if ip not in ips:
                ips.append(ip)
                break

    adj = {ip: set() for ip in ips}

    connected = [ips[0]]
    remaining = ips[1:]
    while remaining:
        ip1 = random.choice(connected)
        ip2 = random.choice(remaining)
        adj[ip1].add(ip2)
        adj[ip2].add(ip1)
        connected.append(ip2)
        remaining.remove(ip2)
    for i in range(len(ips)):
        for j in range(i+1, len(ips)):
            if random.random() < link_prob and ips[j] not in adj[ips[i]]:
                adj[ips[i]].add(ips[j])
                adj[ips[j]].add(ips[i])
    return adj


def build_routers(adj: Dict[str, Set[str]], verbose: bool):
    num = len(adj)
    barrier_send = threading.Barrier(num)
    barrier_recv = threading.Barrier(num)
    step_done   = threading.Barrier(num + 1)
    stop_event  = threading.Event()

    routers: Dict[str, Router] = {}
    for ip in adj:
        routers[ip] = Router(ip, barrier_send, barrier_recv, step_done, stop_event, verbose)

    for ip, nb_ips in adj.items():
        neighbors = [routers[nb] for nb in nb_ips]
        routers[ip].set_neighbors(neighbors)

    return list(routers.values()), stop_event, step_done

def main():
    parser = argparse.ArgumentParser(description="RIP protocol emulator")
    parser.add_argument('--config', type=str, help='JSON file with topology')
    parser.add_argument('--random', type=int, help='Number of routers for random topology')
    parser.add_argument('--steps', type=int, default=20, help='Maximum simulation steps')
    parser.add_argument('--verbose', action='store_true', help='Show intermediate tables (Task B)')
    args = parser.parse_args()

    if args.config:
        with open(args.config, 'r') as f:
            data = json.load(f)
        adj: Dict[str, Set[str]] = {}
        for r in data['routers']:
            ip = r['ip']
            adj[ip] = set(r.get('neighbors', []))
        all_ips = set(adj.keys())
        for ip, nbs in adj.items():
            for nb in nbs:
                if nb not in all_ips:
                    print(f"Error: neighbor {nb} of {ip} not found in routers list")
                    sys.exit(1)
    elif args.random:
        num = args.random
        adj = generate_random_topology(num)
    else:
        adj = {
            "198.71.243.61":  {"42.162.54.248"},
            "42.162.54.248": {"198.71.243.61", "157.105.66.180"},
            "157.105.66.180": {"42.162.54.248", "229.28.61.15"},
            "229.28.61.15":  {"157.105.66.180", "122.136.243.149"},
            "122.136.243.149": {"229.28.61.15"}
        }

    routers, stop_event, step_done = build_routers(adj, verbose=args.verbose)

    for r in routers:
        r.start()

    snap = {r.ip: dict(r.table) for r in routers}
    stop_event.clear()

    max_steps = args.steps
    for step in range(1, max_steps + 1):
        step_done.wait()

        changed = False
        for r in routers:
            if snap[r.ip] != r.table:
                changed = True
                break

        if not changed:
            stop_event.set()
            break
            
        if step == max_steps:
            stop_event.set()

        for r in routers:
            snap[r.ip] = dict(r.table)

        if stop_event.is_set():
            break

    for r in routers:
        r.join(timeout=2)

    print("\n=== Final routing tables ===\n")
    for r in routers:
        r.print_table()

if __name__ == '__main__':
    main()