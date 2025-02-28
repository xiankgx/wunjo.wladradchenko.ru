"""
BSD 3-Clause License

Copyright (c) 2018, NVIDIA Corporation
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

* Neither the name of the copyright holder nor the names of its
  contributors may be used to endorse or promote products derived from
  this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""
import os.path

import yaml


class AttributeDict(dict):
    def __init__(self, dct=None):
        super().__init__()
        dct = dict() if not dct else dct
        for key, value in dct.items():
            if hasattr(value, 'keys'):
                value = AttributeDict(value)
            self[key] = value


    def __getattr__(self, attr):
        return self[attr]


    def __setattr__(self, attr, value):
        self[attr] = value


    def __getstate__(self):
        return self


    def __setstate__(self, state):
        pass


    def export(self):
        return dict(self)


def create_hparams(config_source):
    if isinstance(config_source, dict):
        config = config_source
    elif isinstance(config_source, str):
        with open(config_source, "r", encoding="utf-8") as stream:
            config = yaml.safe_load(stream)

    return AttributeDict(config)


def read_default_hparams():
    root_path = os.path.dirname(os.path.abspath(__file__))
    config_source = os.path.join(root_path, "hparams", "hparams.yaml")
    with open(config_source, "r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    return config


def save_hparams(path, config):
    if isinstance(config, dict):
        hparams_file = os.path.join(path, "started_hparams.yaml")
        with open(hparams_file, "w", encoding="utf-8") as file:
            yaml.dump(config, file)
        return hparams_file
    return None
