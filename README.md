# Synapse

Describe a repetitive task in plain English; Synapse benchmarks rules, classic ML, embeddings and smaller LLMs against NVIDIA Nemotron Ultra, then ships the cheapest specialist that passes, with measured savings.

Built for the Nebius x NVIDIA Global AI Hackathon (Coding and Agentic Engineering track).

**Status:** early build. Setup and run instructions, results and the "Built on Nebius and NVIDIA" section will be added as the build progresses. Platform checks are recorded in [`docs/VERIFICATION.md`](docs/VERIFICATION.md).

## Data sources

The demo specialists in `artifacts/demo/specialists/` are models trained on these public datasets (details and
licenses in `config/datasets.yaml`):

- **Procurement:** USAspending.gov contract award data, U.S. Department of the Treasury, Bureau of the Fiscal
  Service (free to copy, adapt and redistribute; D&B-derived fields are not used), with categories rolled up
  from the federal Product and Service Code manual (acquisition.gov).
- **System logs:** LogHub HDFS_v1 (https://github.com/logpai/loghub), for research use. Cite: Jieming Zhu,
  Shilin He, Pinjia He, Jinyang Liu, Michael R. Lyu. *Loghub: A Large Collection of System Log Datasets for
  AI-driven Log Analytics.* ISSRE 2023; and Wei Xu, Ling Huang, Armando Fox, David Patterson, Michael Jordan.
  *Detecting Large-Scale System Problems by Mining Console Logs.* SOSP 2009. Raw logs are not redistributed
  here; `make demo-data` downloads them.
- **Support tickets:** Banking77 by PolyAI (https://huggingface.co/datasets/PolyAI/banking77), CC-BY-4.0.
  Casanueva et al. *Efficient Intent Detection with Dual Sentence Encoders.* 2020. The model files contain
  vocabulary and an example message derived from it.

## License

Code: MIT. See [LICENSE](LICENSE). Datasets and models derived from them keep their own terms (above).
