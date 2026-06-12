## Description: <br>
Enable MIPI/GMSL camera sensors on a Jetson Thor or Orin custom carrier by rendering a kernel-DT overlay from the in-tree sensor DTSI. <br>

This skill is ready for commercial/non-commercial use. <br>

## Owner: NVIDIA <br>

### License/Terms of Use: <br>
Apache-2.0 <br>
## Use Case: <br>
Developers and engineers use this skill to bring up MIPI CSI-2 and GMSL camera sensors on custom Jetson carrier boards by generating the correct kernel device-tree overlay from NVIDIA's in-tree sensor references. <br>

### Deployment Geography for Use: <br>
Global <br>

## Known Risks and Mitigations: <br>
Risk: Review before execution as proposals could introduce incorrect or misleading guidance into skills. <br>
Mitigation: Review and scan skill before deployment. <br>

## Reference(s): <br>
- [Detailed Procedure (Steps 1-7)](references/procedure.md) <br>
- [CSI / NVCSI / VI DT Binding Reference](references/csi-dt-bindings.md) <br>
- [Camera Overlay Regeneration Recipe](references/overlay-template.md) <br>
- [Camera Overlay Templates](references/camera-overlay-templates/README.md) <br>


## Skill Output: <br>
**Output Type(s):** [Code, Shell commands, Configuration instructions] <br>
**Output Format:** [Device-tree source (.dts) with inline bash code blocks] <br>
**Output Parameters:** [1D] <br>
**Other Properties Related to Output:** [None] <br>

## Skill Version(s): <br>
0.0.1 (source: frontmatter) <br>

## Ethical Considerations: <br>
NVIDIA believes Trustworthy AI is a shared responsibility and we have established policies and practices to enable development for a wide array of AI applications. When downloaded or used in accordance with our terms of service, developers should work with their internal team to ensure this skill meets requirements for the relevant industry and use case and addresses unforeseen product misuse. <br>

(For Release on NVIDIA Platforms Only) <br>
Please report quality, risk, security vulnerabilities or NVIDIA AI Concerns [here](https://app.intigriti.com/programs/nvidia/nvidiavdp/detail). <br>
