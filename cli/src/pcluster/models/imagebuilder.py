# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
#
# This module contains all the classes representing the Resources objects.
# These objects are obtained from the configuration file through a conversion based on the Schema classes.
#

from typing import List

from pcluster import utils
from pcluster.config.extended_builtin_class import MarkedBool
from pcluster.models.cluster import Resource, Tag
from pcluster.validators.ec2_validators import BaseAMIValidator

# ---------------------- Image ---------------------- #


class Volume(Resource):
    """Represent the volume configuration for the ImageBuilder."""

    def __init__(self, size: int = None, encrypted: bool = None, kms_key_id: str = None):
        super().__init__()
        self.size = size
        self.encrypted = encrypted
        self.kms_key_id = kms_key_id
        self._set_defaults()
        # TODO: add validator

    def _set_defaults(self):
        if self.encrypted is None:
            self.encrypted = MarkedBool(False)


class Image(Resource):
    """Represent the image configuration for the ImageBuilder."""

    def __init__(
        self,
        name: str,
        description: str = None,
        tags: List[Tag] = None,
        root_volume: Volume = None,
    ):
        super().__init__()
        self.name = name
        self.description = description
        self.tags = tags
        self.root_volume = root_volume
        self._set_default()
        # TODO: add validator

    def _set_default(self):
        if self.tags is None:
            self.tags = []
        default_tag = Tag("PclusterVersion", utils.get_installed_version())
        default_tag.implied = True
        self.tags.append(default_tag)


# ---------------------- Build ---------------------- #


class Component(Resource):
    """Represent the components configuration for the ImageBuilder."""

    def __init__(self, type: str = None, value: str = None):
        super().__init__()
        self.type = type
        self.value = value
        # TODO: add validator


class Build(Resource):
    """Represent the build configuration for the ImageBuilder."""

    def __init__(
        self,
        instance_type: str,
        parent_image: str,
        instance_role: str = None,  # TODO: auto generate if not assigned
        subnet_id: str = None,  # TODO: auto generate if not assigned
        tags: List[Tag] = None,
        security_group_ids: List[str] = None,
        components: List[Component] = None,
    ):
        super().__init__()
        self.instance_type = instance_type
        self.parent_image = parent_image
        self.instance_role = instance_role
        self.tags = tags
        self.subnet_id = subnet_id
        self.security_group_ids = security_group_ids
        self.components = components
        # TODO: add validator


# ---------------------- Dev Settings ---------------------- #


class ChefCookbook(Resource):
    """Represent the chef cookbook configuration for the ImageBuilder."""

    def __init__(self, url: str, json: str):
        super().__init__()
        self.url = url
        self.json = json
        # TODO: add validator


class DevSettings(Resource):
    """Represent the dev settings configuration for the ImageBuilder."""

    def __init__(
        self,
        update_os_and_reboot: bool = None,
        disable_pcluster_component: bool = None,
        chef_cookbook: ChefCookbook = None,
        node_url: str = None,
        aws_batch_cli_url: str = None,
        distribution_configuration_arn: str = None,
        terminate_instance_on_failure: bool = None,
    ):
        super().__init__()
        self.update_os_and_reboot = update_os_and_reboot
        self.disable_pcluster_component = disable_pcluster_component
        self.chef_cookbook = chef_cookbook
        self.node_url = node_url
        self.aws_batch_cli_url = aws_batch_cli_url
        self.distribution_configuration_arn = distribution_configuration_arn
        self.terminate_instance_on_failure = terminate_instance_on_failure
        self._set_default()
        # TODO: add validator

    def _set_default(self):
        if self.update_os_and_reboot is None:
            self.update_os_and_reboot = MarkedBool(False)
        if self.disable_pcluster_component is None:
            self.disable_pcluster_component = MarkedBool(False)
        if self.terminate_instance_on_failure is None:
            self.terminate_instance_on_failure = MarkedBool(True)


# ---------------------- ImageBuilder ---------------------- #


class ImageBuilder(Resource):
    """Represent the configuration of an ImageBuilder."""

    def __init__(
        self,
        image: Image,
        build: Build,
        dev_settings: DevSettings = None,
    ):
        super().__init__()
        self.image = image
        self.build = build
        self.dev_settings = dev_settings
        self._add_validator(BaseAMIValidator, ami_id=self.build.parent_image)