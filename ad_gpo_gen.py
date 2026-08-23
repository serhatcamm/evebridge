"""
Active Directory / Group Policy bootstrap generator
------------------------------------------------------
Produces ready-to-run elevated PowerShell for lab Domain Controllers and
domain members on Windows Server (Core fully supported - everything here is
cmdlet-based, no GUI required):

  - Promote a server to the first DC of a new forest (Install-ADDSForest)
  - Join a machine to the domain (DNS-first, then Add-Computer)
  - Create the usual lab OUs / groups / users
  - Create + link a baseline GPO with common registry tweaks

Pairs naturally with the AAA tab: NPS (RADIUS) authenticates against these
exact AD users/groups.
"""


def _dn(domain: str) -> str:
    """'lab.local' -> 'DC=lab,DC=local'"""
    parts = [p for p in domain.strip().split(".") if p]
    return ",".join(f"DC={p}" for p in parts)


def build_dc_promo(domain: str, netbios: str, dsrm_pass: str) -> str:
    domain = domain.strip() or "lab.local"
    netbios = netbios.strip() or domain.split(".")[0].upper()
    return (
        "# ============================================================\n"
        "# Promote this Windows Server to the first DC of a new forest\n"
        "# (elevated PowerShell - works on Server Core)\n"
        "# ============================================================\n"
        "Install-WindowsFeature AD-Domain-Services -IncludeManagementTools\n\n"
        "$dsrm = ConvertTo-SecureString '" + dsrm_pass + "' -AsPlainText -Force\n"
        "Install-ADDSForest `\n"
        "  -DomainName '" + domain + "' `\n"
        "  -DomainNetbiosName '" + netbios + "' `\n"
        "  -SafeModeAdministratorPassword $dsrm `\n"
        "  -InstallDns:$true -NoRebootOnCompletion:$false -Force\n\n"
        "# After the reboot, verify:\n"
        "Get-ADDomain | Select-Object Forest, Domain, DNSRoot\n"
        "Get-Service NTDS, Netlogon, kdc\n"
    )


def build_domain_join(domain: str, dc_ip: str) -> str:
    domain = domain.strip() or "lab.local"
    return (
        "# ============================================================\n"
        "# Join this machine to the domain (elevated PowerShell)\n"
        "# ============================================================\n"
        "# 1) Point DNS at the DC first - domain join fails without it:\n"
        "$nic = Get-NetAdapter | Where-Object Status -eq 'Up'\n"
        "Set-DnsClientServerAddress -InterfaceIndex $nic.ifIndex -ServerAddresses '"
        + (dc_ip.strip() or "<DC_IP>") + "'\n\n"
        "# 2) Join and reboot:\n"
        "$cred = Get-Credential  # DOMAIN\\administrator\n"
        "Add-Computer -DomainName '" + domain + "' -DomainCredential $cred -Restart -Force\n\n"
        "# Verify after reboot:\n"
        "(Get-WmiObject Win32_ComputerSystem).PartOfDomain\n"
    )


def build_users_groups(domain: str, netbios: str,
                       admin_user: str, admin_pass: str) -> str:
    domain = domain.strip() or "lab.local"
    netbios = netbios.strip() or domain.split(".")[0].upper()
    dn = _dn(domain)
    return (
        "# ============================================================\n"
        "# Lab OUs / groups / users (run on the DC, elevated PowerShell)\n"
        "# ============================================================\n"
        "Import-Module ActiveDirectory\n\n"
        "New-ADOrganizationalUnit -Name 'Lab' -Path '" + dn + "'\n"
        "New-ADGroup -Name 'NetAdmins' -GroupScope Global "
        "-Path 'OU=Lab," + dn + "'\n\n"
        "$pwd_" + netbios + " = ConvertTo-SecureString '" + admin_pass + "' -AsPlainText -Force\n"
        "New-ADUser -Name '" + admin_user + "' -SamAccountName '" + admin_user + "' `\n"
        "  -Path 'OU=Lab," + dn + "' `\n"
        "  -AccountPassword $pwd_" + netbios + " -Enabled $true -PasswordNeverExpires $true\n\n"
        "Add-ADGroupMember -Identity 'NetAdmins' -Members '" + admin_user + "'\n\n"
        "# This NetAdmins group is exactly what you allow in the NPS network\n"
        "# policy on the AAA tab (RADIUS -> AD).\n\n"
        "# Verify:\n"
        "Get-ADUser -Filter * | Select Name, SamAccountName, Enabled\n"
    )


def build_gpo_starter(gpo_name: str, domain: str) -> str:
    gpo_name = gpo_name.strip() or "Lab-Base"
    dn = _dn(domain)
    return (
        "# ============================================================\n"
        "# Baseline GPO: create, link to the Lab OU, apply common settings\n"
        "# (run on the DC; needs GPMC - installed with AD-Domain-Services)\n"
        "# ============================================================\n"
        "Import-Module GroupPolicy\n"
        "New-GPO -Name '" + gpo_name + "' | New-GPLink -Target 'OU=Lab," + dn +
        "' -LinkEnabled Yes -Order 1\n\n"
        "# Enable Remote Desktop:\n"
        "Set-GPRegistryValue -Name '" + gpo_name + "' `\n"
        "  -Key 'HKLM\\SYSTEM\\CurrentControlSet\\Control\\Terminal Server' `\n"
        "  -ValueName fDenyTSConnections -Type DWord -Value 0\n"
        "Set-GPRegistryValue -Name '" + gpo_name + "' `\n"
        "  -Key 'HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows NT\\Terminal Services' `\n"
        "  -ValueName UserAuthentication -Type DWord -Value 1\n\n"
        "# Show hidden files + file extensions for all users:\n"
        "Set-GPRegistryValue -Name '" + gpo_name + "' `\n"
        "  -Key 'HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced' `\n"
        "  -ValueName Hidden -Type DWord -Value 1\n"
        "Set-GPRegistryValue -Name '" + gpo_name + "' `\n"
        "  -Key 'HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced' `\n"
        "  -ValueName HideFileExt -Type DWord -Value 0\n\n"
        "# Force the policy on clients:\n"
        "#   gpupdate /force      (on a member machine)\n\n"
        "# Inspect / back up:\n"
        "Get-GPOReport -Name '" + gpo_name + "' -ReportType Html -Path '.\\" + gpo_name + ".html'\n"
        "Backup-GPO -Name '" + gpo_name + "' -Path '.\\gpo-backups'\n"
    )
