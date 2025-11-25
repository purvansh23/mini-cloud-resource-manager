def calculate_host_score(metric):
    """
    Convert CPU %, MEM %, and running VMs into normalized weighted score.
    Used by the scheduler to rank hosts for VM placement.

    Weights:
        CPU  → 0.5
        MEM  → 0.3
        VM Count → 0.2
    """

    # Raw values
    cpu = float(metric.cpu_percent or 0)      # range: 0–100
    mem = float(metric.mem_percent or 0)      # range: 0–100
    vms = int(metric.vms_running or 0)        # number of running VMs

    # Normalization
    cpu_norm = cpu / 100.0
    mem_norm = mem / 100.0

    # Cap VM count influence at 1.0 (i.e., >=10 VMs treated equally)
    vmc_norm = min(vms / 10.0, 1.0)

    # Weighted score (lower is better → less loaded)
    score = (cpu_norm * 0.5) + \
            (mem_norm * 0.3) + \
            (vmc_norm * 0.2)

    return {
        "cpu_norm": cpu_norm,
        "mem_norm": mem_norm,
        "vmc_norm": vmc_norm,
        "score": score,
    }
