## Description: <br>
Enable/disable Jetson USB2/USB3 SS ports via kernel-DT overlay. <br>

This skill is ready for commercial/non-commercial use. <br>

## Owner: NVIDIA <br>

### License/Terms of Use: <br>
Apache 2.0 AND CC-BY-4.0 <br>
## Use Case: <br>
Developers and engineers customizing per-port USB2/USB3 enable, disable, or role assignment on NVIDIA Jetson custom carrier boards via guided kernel device-tree overlay generation. <br>

### Deployment Geography for Use: <br>
Global <br>

## Known Risks and Mitigations: <br>
Risk: Review before execution as proposals could introduce incorrect or misleading guidance into skills. <br>
Mitigation: Review and scan skill before deployment. <br>

## Reference(s): <br>
- [USB Architecture](references/usb-architecture.md) <br>
- [USB DT Bindings](references/usb-dt-bindings.md) <br>
- [Procedure](references/procedure.md) <br>
- [Gotchas](references/gotchas.md) <br>
- [Run-State Sidecar](references/run-state-sidecar.md) <br>


## Skill Output: <br>
**Output Type(s):** [Code, Files, Configuration instructions] <br>
**Output Format:** [Device Tree Source (DTS) overlay and JSON sidecar] <br>
**Output Parameters:** [1D] <br>
**Other Properties Related to Output:** [Commits rendered overlay to bsp_sources repository] <br>

## Skill Version(s): <br>
0.0.1 (source: frontmatter) <br>

## Ethical Considerations: <br>
NVIDIA believes Trustworthy AI is a shared responsibility and we have established policies and practices to enable development for a wide array of AI applications. When downloaded or used in accordance with our terms of service, developers should work with their internal team to ensure this skill meets requirements for the relevant industry and use case and addresses unforeseen product misuse. <br>

(For Release on NVIDIA Platforms Only) <br>
Please report quality, risk, security vulnerabilities or NVIDIA AI Concerns [here](https://app.intigriti.com/programs/nvidia/nvidiavdp/detail). <br>
