## Description: <br>
Extract Jetson Linux + sample-rootfs tarballs and run apply_binaries.sh for the active target, then record bsp_image in the profile. <br>

This skill is ready for commercial/non-commercial use. <br>

## Owner: NVIDIA <br>

### License/Terms of Use: <br>
Apache 2.0 AND CC-BY-4.0 <br>
## Use Case: <br>
Developers and engineers use this skill to extract Jetson Linux BSP tarballs, apply binaries with the correct GPU-stack flag, and record the resulting image path in the active target profile. <br>

### Deployment Geography for Use: <br>
Global <br>

## Known Risks and Mitigations: <br>
Risk: Review before execution as proposals could introduce incorrect or misleading guidance into skills. <br>
Mitigation: Review and scan skill before deployment. <br>

## Reference(s): <br>
- [Target Platform Contract](../../context/target-platform-contract.md) <br>
- [BSP Platforms Catalogue](../../references/bsp-platforms-catalogue.md) <br>
- [Platform Template](../../references/platform_template.yaml) <br>
- [Jetson Init Target Skill](../jetson-init-target/SKILL.md) <br>
- [Jetson Init Source Skill](../jetson-init-source/SKILL.md) <br>
- [Jetson Flash Image Skill](../jetson-flash-image/SKILL.md) <br>


## Skill Output: <br>
**Output Type(s):** [Shell commands, Configuration instructions] <br>
**Output Format:** [Markdown with inline bash code blocks] <br>
**Output Parameters:** [1D] <br>
**Other Properties Related to Output:** [None] <br>

## Skill Version(s): <br>
0.0.1 (source: frontmatter) <br>

## Ethical Considerations: <br>
NVIDIA believes Trustworthy AI is a shared responsibility and we have established policies and practices to enable development for a wide array of AI applications. When downloaded or used in accordance with our terms of service, developers should work with their internal team to ensure this skill meets requirements for the relevant industry and use case and addresses unforeseen product misuse. <br>

(For Release on NVIDIA Platforms Only) <br>
Please report quality, risk, security vulnerabilities or NVIDIA AI Concerns [here](https://app.intigriti.com/programs/nvidia/nvidiavdp/detail). <br>
