import paramiko

def run_ssh_command(host, username, password, command):
    """
    Executes a single SSH command and returns stdout.
    Raises an exception if exit status != 0.
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=username, password=password, timeout=10)
    stdin, stdout, stderr = client.exec_command(command)
    output = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    retcode = stdout.channel.recv_exit_status()
    client.close()

    if retcode != 0:
        raise RuntimeError(f"Command failed ({retcode}): {command}\nError: {err}")
    return output


def get_sr_uuid(host, user, password, sr_name):
    cmd = f"xe sr-list name-label='{sr_name}' params=uuid --minimal"
    return run_ssh_command(host, user, password, cmd)


def get_iso_vdi_uuid(host, user, password, iso_name):
    cmd = f"xe vdi-list name-label='{iso_name}' params=uuid --minimal"
    return run_ssh_command(host, user, password, cmd)


def create_vm_from_iso(host, user, password, vm_name, iso_name, sr_name, network_name, ram_mb=2048, vcpus=2):
    """
    Creates a VM that boots from an ISO.
    Steps:
    1. Find the ISO VDI UUID and SR UUID.
    2. Create a new VM.
    3. Create a VDI for disk.
    4. Attach disk and ISO as CD.
    5. Add NIC.
    6. Start VM.
    Returns: dict with created resource UUIDs.
    """
    # Step 1: lookup SR and ISO
    sr_uuid = get_sr_uuid(host, user, password, sr_name)
    iso_vdi_uuid = get_iso_vdi_uuid(host, user, password, iso_name)
    if not sr_uuid:
        raise RuntimeError(f"Storage repository '{sr_name}' not found on host {host}")
    if not iso_vdi_uuid:
        raise RuntimeError(f"ISO '{iso_name}' not found in SR '{sr_name}'")

    # Step 2: create VM
    vm_uuid = run_ssh_command(host, user, password, f"xe vm-create name-label='{vm_name}' memory-static-max={ram_mb*1024*1024} memory-dynamic-max={ram_mb*1024*1024} VCPUs-max={vcpus} VCPUs-at-startup={vcpus}")

    # Step 3: create disk VDI (20 GB default)
    vdi_uuid = run_ssh_command(host, user, password, f"xe vdi-create sr-uuid={sr_uuid} name-label='{vm_name}-disk' type=user virtual-size={20*1024*1024*1024}")

    # Step 4: attach VDI and ISO
    run_ssh_command(host, user, password, f"xe vbd-create vm-uuid={vm_uuid} vdi-uuid={vdi_uuid} device=0 bootable=true mode=RW type=Disk")
    run_ssh_command(host, user, password, f"xe vbd-create vm-uuid={vm_uuid} vdi-uuid={iso_vdi_uuid} device=1 bootable=false mode=RO type=CD")

    # Step 5: attach NIC
    network_uuid = run_ssh_command(host, user, password, f"xe network-list name-label='{network_name}' params=uuid --minimal")
    if not network_uuid:
        raise RuntimeError(f"Network '{network_name}' not found on host {host}")
    run_ssh_command(host, user, password, f"xe vif-create vm-uuid={vm_uuid} network-uuid={network_uuid} device=0")

    # Step 6: start VM
    run_ssh_command(host, user, password, f"xe vm-start uuid={vm_uuid}")

    return {
        "vm_uuid": vm_uuid,
        "vdi_uuid": vdi_uuid,
        "iso_vdi_uuid": iso_vdi_uuid,
        "sr_uuid": sr_uuid,
        "network_uuid": network_uuid
    }
