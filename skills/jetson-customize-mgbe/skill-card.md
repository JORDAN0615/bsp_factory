## Description: <br>
Enable Jetson Thor 25G/10G/1G MGBE QSFP via kernel-DT overlay. <br>

This skill is ready for commercial/non-commercial use. <br>

## Owner: NVIDIA <br>

### License/Terms of Use: <br>
Apache 2.0 AND CC-BY-4.0 <br>
## Use Case: <br>
Developers and engineers use this skill to configure MGBE (Multi-Gigabit Ethernet) controllers on NVIDIA Jetson Thor custom carriers, generating kernel device-tree overlays that enable 25G/10G/1G QSFP connectivity with appropriate PHY plumbing. <br>

### Deployment Geography for Use: <br>
Global <br>

## Known Risks and Mitigations: <br>
Risk: Review before execution as proposals could introduce incorrect or misleading guidance into skills. <br>
Mitigation: Review and scan skill before deployment. <br>

## Reference(s): <br>
- [Procedure Reference](references/procedure.md) <br>
- [Questions Schema](references/questions.json) <br>


## Skill Output: <br>
**Output Type(s):** [Code, Shell commands, Configuration instructions] <br>
**Output Format:** [Device-tree source overlays (.dts) with inline bash verification commands] <br>
**Output Parameters:** [1D] <br>
**Other Properties Related to Output:** [Produces git commits to the bsp_sources hardware repo and a JSON run-state sidecar] <br>

## Skill Version(s): <br>
0.0.1 (source: frontmatter) <br>

## Ethical Considerations: <br>
NVIDIA believes Trustworthy AI is a shared responsibility and we have established policies and practices to enable development for a wide array of AI applications. When downloaded or used in accordance with our terms of service, developers should work with their internal team to ensure this skill meets requirements for the relevant industry and use case and addresses unforeseen product misuse. <br>

(For Release on NVIDIA Platforms Only) <br>
Please report quality, risk, security vulnerabilities or NVIDIA AI Concerns [here](https://app.intigriti.com/programs/nvidia/nvidiavdp/detail). <br>
