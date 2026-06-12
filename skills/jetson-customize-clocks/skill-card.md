## Description: <br>
Use to lock/cap Jetson CPU/GPU/EMC clocks, toggle EMC/CPU DVFS, or change cpufreq governors by editing BPMP DTB and nvpower.sh pre-flash. <br>

This skill is ready for commercial/non-commercial use. <br>

## Owner: NVIDIA <br>

### License/Terms of Use: <br>
Apache 2.0 AND CC-BY-4.0 <br>
## Use Case: <br>
Developers and engineers use this skill to customize CPU, GPU, and EMC clock behavior on Jetson targets by editing BPMP DTB and nvpower.sh files before flashing, enabling locked frequencies, DVFS toggling, and governor changes for performance testing or production deployments. <br>

### Deployment Geography for Use: <br>
Global <br>

## Known Risks and Mitigations: <br>
Risk: Review before execution as proposals could introduce incorrect or misleading guidance into skills. <br>
Mitigation: Review and scan skill before deployment. <br>

## Reference(s): <br>
- [BPMP DTB Clock Edits](references/bpmp-dtb-clock-edits.md) <br>
- [Clock Control Model](references/clock-control-model.md) <br>
- [EMC DVFS Disable](references/emc-dvfs-disable.md) <br>
- [nvpower.sh Edits](references/nvpower-sh-edits.md) <br>


## Skill Output: <br>
**Output Type(s):** [Shell commands, Configuration instructions, Files] <br>
**Output Format:** [Markdown with inline bash code blocks and DTS snippets] <br>
**Output Parameters:** [1D] <br>
**Other Properties Related to Output:** [None] <br>

## Skill Version(s): <br>
0.0.1 (source: frontmatter) <br>

## Ethical Considerations: <br>
NVIDIA believes Trustworthy AI is a shared responsibility and we have established policies and practices to enable development for a wide array of AI applications. When downloaded or used in accordance with our terms of service, developers should work with their internal team to ensure this skill meets requirements for the relevant industry and use case and addresses unforeseen product misuse. <br>

(For Release on NVIDIA Platforms Only) <br>
Please report quality, risk, security vulnerabilities or NVIDIA AI Concerns [here](https://app.intigriti.com/programs/nvidia/nvidiavdp/detail). <br>
