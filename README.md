# tinyman-amm-contracts-v2
Tinyman AMM Contracts V2

Tinyman is an automated market maker (AMM) implementation on Algorand.


### Contracts
The contracts are written in [Tealish](https://github.com/Hipo/tealish).

The annotated TEAL outputs and compiled bytecode are available in the [build](contracts/build/) folder.

The Tealish source can be compiled as follows:
```
    tealish contracts/
```
The `.teal` files will be output to the `contracts/build` directory.

A VS Code extension for syntax highlighting of Tealish & TEAL is available [here](https://www.dropbox.com/s/zn3swrfxkyyelpi/tealish-0.0.1.vsix?dl=0)


### Tests
Tests are included in the `tests/` directory. [AlgoJig](https://github.com/Hipo/algojig) and [Tealish](https://github.com/Hipo/tealish) are required to run the tests.

Set up a new virtualenv and install AlgoJig & Tealish into the venv by cloning the (private) repos and install with `pip install /path/to/repo`.
Install the remaining requirements with `pip install -r requirements.txt`

```
    python -m unittest tests.test
```

### Docs

TODO

Docs describing the transactions for each operation are located in the [docs](docs/) folder.

Further documentation is available at [docs.tinyman.org](https://docs.tinyman.org)

### Bug Bounty Program
Please see details in the blog post announcing the program:
https://tinymanorg.medium.com/tinyman-bug-bounty-campaign-b6c5e1ba7d6c

Reports of potential flaws must be responsibly disclosed to `security@tinyman.org`. Do not share details with anyone else until notified to do so by the team.

### Audit
TODO


### Internal Review
TODO


### Acknowledgements
TODO

### Licensing

The contents of this repository are licensed under the Business Source License 1.1 (BUSL-1.1), see [LICENSE](LICENSE).