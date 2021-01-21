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

import operator
from abc import ABC
from enum import Enum
from typing import List

from pcluster.config.extended_builtin_class import MarkedBool, MarkedInt, MarkedStr
from pcluster.constants import CIDR_ALL_IPS, EBS_VOLUME_TYPE_IOPS_DEFAULT
from pcluster.validators.common import ValidationResult, Validator
from pcluster.validators.ebs import EbsVolumeIopsValidator, EbsVolumeThroughputValidator, EbsVolumeTypeSizeValidator
from pcluster.validators.ec2 import InstanceTypeValidator
from pcluster.validators.fsx import FsxValidator


class _ResourceValidator:
    """Represent a generic validator for a resource attribute or object. It's a module private class."""

    def __init__(self, validator_class: Validator, priority: int = 1, **kwargs):
        """Initialize validator. Note: Validators with higher priorities will be executed first."""
        self.validator_class = validator_class
        self.priority = priority
        self.validator_args = kwargs


class Resource(ABC):
    """Represent an abstract Resource entity."""

    def __init__(self):
        self.__validators: List[_ResourceValidator] = []
        self._validation_failures: List[ValidationResult] = []

    def validate(self, raise_on_error=False):
        """Execute registered validators, ordered by priority (high prio --> executed first)."""
        # order validators by priority
        self.__validators = sorted(self.__validators, key=operator.attrgetter("priority"), reverse=True)

        # execute validators and add results in validation_failures array
        for attr_validator in self.__validators:
            # execute it by passing all the arguments
            self._validation_failures.extend(
                attr_validator.validator_class(raise_on_error=raise_on_error)(**attr_validator.validator_args)
            )

        return self._validation_failures

    def _add_validator(self, validator_class: Validator, priority: int = 1, **kwargs):
        """Store validator to be executed at validation execution."""
        self.__validators.append(_ResourceValidator(validator_class, priority=priority, **kwargs))

    def __repr__(self):
        """Return a human readable representation of the Resource object."""
        return "<{name}({attributes})>".format(
            name=self.__class__.__name__,
            attributes=",".join(f"{attr}={value}" for attr, value in self.__dict__.items()),
        )


# ---------------------- Storage ---------------------- #


class Ebs(Resource):
    """Represent the configuration shared by EBS root volume and Shared EBS."""

    def __init__(
        self,
        volume_type: str = None,
        iops: int = None,
        size: int = None,
        encrypted: bool = None,
        kms_key_id: str = None,
        throughput: int = None,
    ):
        super().__init__()
        if volume_type is None:
            volume_type = MarkedStr("gp2")
        if iops is None and volume_type in EBS_VOLUME_TYPE_IOPS_DEFAULT:
            iops = EBS_VOLUME_TYPE_IOPS_DEFAULT.get(volume_type)
        if size is None:
            size = MarkedInt(20)
        if encrypted is None:
            encrypted = MarkedBool(False)
        if throughput is None and volume_type == "gp3":
            throughput = MarkedInt(125)
        self.volume_type = volume_type
        self.iops = iops
        self.size = size
        self.encrypted = encrypted
        self.kms_key_id = kms_key_id
        self.throughput = throughput

        self._add_validator(
            EbsVolumeTypeSizeValidator, priority=10, volume_type=self.volume_type, volume_size=self.size
        )
        self._add_validator(
            EbsVolumeThroughputValidator,
            volume_type=self.volume_type,
            volume_iops=self.iops,
            volume_throughput=self.throughput,
        )
        self._add_validator(
            EbsVolumeIopsValidator,
            volume_type=self.volume_type,
            volume_size=self.size,
            volume_iops=self.iops,
        )


class Raid(Resource):
    """Represent the Raid configuration."""

    def __init__(self, type: str = None, number_of_volumes=None):
        super().__init__()
        if number_of_volumes is None:
            number_of_volumes = MarkedInt(2)
        self.type = type
        self.number_of_volumes = number_of_volumes


class EphemeralVolume(Resource):
    """Represent the Ephemeral Volume resource."""

    def __init__(self, encrypted: bool = None, mount_dir: str = None):
        super().__init__()
        if encrypted is None:
            encrypted = MarkedBool(False)
        if mount_dir is None:
            mount_dir = MarkedStr("/scratch")
        self.encrypted = encrypted
        self.mount_dir = mount_dir


class Storage(Resource):
    """Represent the entire node storage configuration."""

    def __init__(self, root_volume: Ebs = None, ephemeral_volume: EphemeralVolume = None):
        super().__init__()
        self.root_volume = root_volume
        self.ephemeral_volume = ephemeral_volume


class SharedStorage(Resource):
    """Represent a generic shared Storage resource."""

    class Type(Enum):
        """Define storage types to be used as shared storage."""

        EBS = "ebs"
        EFS = "efs"
        FSX = "fsx"

    def __init__(self, mount_dir: str, shared_storage_type: Type):
        super().__init__()
        self.mount_dir = mount_dir
        self.shared_storage_type = shared_storage_type


class SharedEbs(SharedStorage, Ebs):
    """Represent a shared EBS, inherits from both _SharedStorage and Ebs classes."""

    def __init__(
        self,
        mount_dir: str,
        volume_type: str = None,
        iops: int = None,
        size: int = None,
        encrypted: bool = None,
        kms_key_id: str = None,
        throughput: int = None,
        snapshot_id: str = None,
        volume_id: str = None,
        raid: Raid = None,
    ):
        SharedStorage.__init__(self, mount_dir=mount_dir, shared_storage_type=SharedStorage.Type.EBS)
        Ebs.__init__(self, volume_type, iops, size, encrypted, kms_key_id, throughput)
        self.snapshot_id = snapshot_id
        self.volume_id = volume_id
        self.raid = raid


class SharedEfs(SharedStorage):
    """Represent the shared EFS resource."""

    def __init__(
        self,
        mount_dir: str,
        encrypted: bool = None,
        kms_key_id: str = None,
        performance_mode: str = None,
        throughput_mode: str = None,
        provisioned_throughput: int = None,
        id: str = None,
    ):
        super().__init__(mount_dir=mount_dir, shared_storage_type=SharedStorage.Type.EFS)
        if encrypted is None:
            encrypted = MarkedBool(False)
        if performance_mode is None:
            performance_mode = MarkedStr("generalPurpose")
        if throughput_mode is None:
            throughput_mode = MarkedStr("bursting")
        self.encrypted = encrypted
        self.kms_key_id = kms_key_id
        self.performance_mode = performance_mode
        self.throughput_mode = throughput_mode
        self.provisioned_throughput = provisioned_throughput
        self.id = id


class SharedFsx(SharedStorage):
    """Represent the shared FSX resource."""

    def __init__(
        self,
        mount_dir: str,
        storage_capacity: str = None,
        deployment_type: str = None,
        export_path: str = None,
        import_path: str = None,
        imported_file_chunk_size: str = None,
        weekly_maintenance_start_time: str = None,
        automatic_backup_retention_days: str = None,
        copy_tags_to_backups: bool = None,
        daily_automatic_backup_start_time: str = None,
        per_unit_storage_throughput: int = None,
        backup_id: str = None,
        kms_key_id: str = None,
        file_system_id: str = None,
        auto_import_policy: str = None,
        drive_cache_type: str = None,
        storage_type: str = None,
    ):
        super().__init__(mount_dir=mount_dir, shared_storage_type=SharedStorage.Type.FSX)
        self.storage_capacity = storage_capacity
        self.storage_type = storage_type
        self.deployment_type = deployment_type
        self.export_path = export_path
        self.import_path = import_path
        self.imported_file_chunk_size = imported_file_chunk_size
        self.weekly_maintenance_start_time = weekly_maintenance_start_time
        self.automatic_backup_retention_days = automatic_backup_retention_days
        self.copy_tags_to_backups = copy_tags_to_backups
        self.daily_automatic_backup_start_time = daily_automatic_backup_start_time
        self.per_unit_storage_throughput = per_unit_storage_throughput
        self.backup_id = backup_id
        self.kms_key_id = kms_key_id
        self.file_system_id = file_system_id
        self.auto_import_policy = auto_import_policy
        self.drive_cache_type = drive_cache_type
        self.storage_type = storage_type
        self._add_validator(FsxValidator, fsx_config=self)
        # TODO decide whether we should split FsxValidator into smaller ones


# ---------------------- Networking ---------------------- #


class Proxy(Resource):
    """Represent the proxy."""

    def __init__(self, http_proxy_address: str = None):
        super().__init__()
        self.http_proxy_address = http_proxy_address


class BaseNetworking(Resource):
    """Represent the networking configuration shared by head node and compute node."""

    def __init__(
        self,
        assign_public_ip: str = None,
        security_groups: List[str] = None,
        additional_security_groups: List[str] = None,
        proxy: Proxy = None,
    ):
        super().__init__()
        self.assign_public_ip = assign_public_ip
        self.security_groups = security_groups
        self.additional_security_groups = additional_security_groups
        self.proxy = proxy


class HeadNodeNetworking(BaseNetworking):
    """Represent the networking configuration for the head node."""

    def __init__(self, subnet_id: str, elastic_ip: str = None, **kwargs):
        super().__init__(**kwargs)
        self.subnet_id = subnet_id
        self.elastic_ip = elastic_ip


class PlacementGroup(Resource):
    """Represent the placement group for the Queue networking."""

    def __init__(self, enabled: bool = None, id: str = None):
        super().__init__()
        if enabled is None:
            enabled = MarkedBool(False)
        self.enabled = enabled
        self.id = id


class QueueNetworking(BaseNetworking):
    """Represent the networking configuration for the Queue."""

    def __init__(self, subnet_ids: List[str], placement_group: PlacementGroup = None, **kwargs):
        super().__init__(**kwargs)
        self.subnet_ids = subnet_ids
        self.placement_group = placement_group


class Ssh(Resource):
    """Represent the SSH configuration for a node (or the entire cluster)."""

    def __init__(self, key_name: str, allowed_ips: str = None):
        super().__init__()
        if allowed_ips is None:
            allowed_ips = MarkedStr(CIDR_ALL_IPS)
        self.key_name = key_name
        self.allowed_ips = allowed_ips


class Dcv(Resource):
    """Represent the DCV configuration."""

    def __init__(self, enabled: bool, port: int = None, allowed_ips: str = None):
        super().__init__()
        if port is None:
            port = MarkedInt(8843)
        if allowed_ips is None:
            allowed_ips = MarkedStr(CIDR_ALL_IPS)
        self.enabled = enabled
        self.port = port
        self.allowed_ips = allowed_ips


# ---------------------- Nodes ---------------------- #


class Image(Resource):
    """Represent the configuration of an Image."""

    def __init__(self, os: str, custom_ami: str = None):
        super().__init__()
        self.os = os
        self.custom_ami = custom_ami


class HeadNode(Resource):
    """Represent the Head Node resource."""

    def __init__(
        self,
        instance_type: str,
        networking: HeadNodeNetworking,
        ssh: Ssh,
        image: Image = None,
        storage: Storage = None,
        dcv: Dcv = None,
    ):
        super().__init__()
        self.instance_type = instance_type
        self.image = image
        self.networking = networking
        self.ssh = ssh
        self.storage = storage
        self.dcv = dcv
        self._add_validator(InstanceTypeValidator, priority=1, instance_type=self.instance_type)


class ComputeResource(Resource):
    """Represent the Compute Resource."""

    def __init__(self, instance_type: str, max_count: int = None):
        super().__init__()
        if max_count is None:
            max_count = MarkedInt(10)
        self.instance_type = instance_type
        self.max_count = max_count
        # TODO add missing attributes


class Queue(Resource):
    """Represent the Queue resource."""

    def __init__(self, name: str, networking: QueueNetworking, compute_resources: List[ComputeResource]):
        super().__init__()
        self.name = name
        self.networking = networking
        self.compute_resources = compute_resources


class SchedulingSettings(Resource):
    """Represent the Scheduling configuration."""

    def __init__(self, scaledown_idletime: int):
        super().__init__()
        self.scaledown_idletime = scaledown_idletime


class Scheduling(Resource):
    """Represent the Scheduling configuration."""

    def __init__(self, queues: List[Queue], scheduler: str = None, settings: SchedulingSettings = None):
        super().__init__()
        if scheduler is None:
            scheduler = MarkedStr("slurm")
        self.scheduler = scheduler
        self.queues = queues
        self.settings = settings


class CustomAction(Resource):
    """Represent a custom action resource."""

    def __init__(self, script: str, args: List[str] = None, event: str = None, run_as: str = None):
        super().__init__()
        self.script = script
        self.args = args
        self.event = event
        self.run_as = run_as


# ---------------------- Monitoring ---------------------- #


class CloudWatchLogs(Resource):
    """Represent the CloudWatch configuration in Logs."""

    def __init__(
        self,
        enabled: bool = None,
        retention_in_days: int = None,
        log_group_id: str = None,
        kms_key_id: str = None,
    ):
        super().__init__()
        if enabled is None:
            enabled = MarkedBool(True)
        if retention_in_days is None:
            retention_in_days = MarkedInt(14)
        self.enabled = enabled
        self.retention_in_days = retention_in_days
        self.log_group_id = log_group_id
        self.kms_key_id = kms_key_id


class CloudWatchDashboards(Resource):
    """Represent the CloudWatch Dashboard."""

    def __init__(
        self,
        enabled: bool = None,
    ):
        super().__init__()
        if enabled is None:
            enabled = MarkedBool(True)
        self.enabled = enabled


class Logs(Resource):
    """Represent the CloudWatch Logs configuration."""

    def __init__(
        self,
        cloud_watch: CloudWatchLogs = None,
    ):
        super().__init__()
        self.cloud_watch = cloud_watch


class Dashboards(Resource):
    """Represent the Dashboards configuration."""

    def __init__(
        self,
        cloud_watch: CloudWatchDashboards = None,
    ):
        super().__init__()
        self.cloud_watch = cloud_watch


class Monitoring(Resource):
    """Represent the Monitoring configuration."""

    def __init__(
        self,
        detailed_monitoring: bool = None,
        logs: Logs = None,
        dashboards: Dashboards = None,
    ):
        super().__init__()
        if detailed_monitoring is None:
            detailed_monitoring = MarkedBool(False)
        self.detailed_monitoring = detailed_monitoring
        self.logs = logs
        self.dashboards = dashboards


# ---------------------- Others ---------------------- #


class Roles(Resource):
    """Represent the Roles configuration."""

    def __init__(
        self,
        head_node: str = None,
        compute_node: str = None,
        custom_lambda_resources: str = None,
    ):
        super().__init__()
        if head_node is None:
            head_node = MarkedStr("AUTO")
        if compute_node is None:
            compute_node = MarkedStr("AUTO")
        if custom_lambda_resources is None:
            custom_lambda_resources = MarkedStr("AUTO")
        self.head_node = head_node
        self.compute_node = compute_node
        self.custom_lambda_resources = custom_lambda_resources


class S3Access(Resource):
    """Represent the S3 Access configuration."""

    def __init__(
        self,
        bucket_name: str,
        type: str = None,
    ):
        super().__init__()
        if type is None:
            type = MarkedStr("READ_ONLY")
        self.bucket_name = bucket_name
        self.type = type


class AdditionalIamPolicy(Resource):
    """Represent the Additional IAM Policy configuration."""

    def __init__(
        self,
        policy: str,
        scope: str = None,
    ):
        super().__init__()
        if scope is None:
            scope = MarkedStr("CLUSTER")
        self.policy = policy
        self.scope = scope


class Iam(Resource):
    """Represent the IAM configuration."""

    def __init__(
        self,
        roles: Roles = None,
        s3_access: List[S3Access] = None,
        additional_iam_policies: List[AdditionalIamPolicy] = None,
    ):
        super().__init__()
        self.roles = roles
        self.s3_access = s3_access
        self.additional_iam_policies = additional_iam_policies


class Tag(Resource):
    """Represent the Tag configuration."""

    def __init__(
        self,
        key: str = None,
        value: str = None,
    ):
        super().__init__()
        self.key = key
        self.value = value


# ---------------------- Root resource ---------------------- #


class Cluster(Resource):
    """Represent the full Cluster configuration."""

    def __init__(
        self,
        image: Image,
        head_node: HeadNode,
        scheduling: Scheduling,
        shared_storage: List[SharedStorage] = None,
        monitoring: Monitoring = None,
        tags: List[Tag] = None,
        iam: Iam = None,
        custom_actions: CustomAction = None,
    ):
        super().__init__()
        self.image = image
        self.head_node = head_node
        self.scheduling = scheduling
        self.shared_storage = shared_storage
        self.monitoring = monitoring
        self.tags = tags
        self.iam = iam
        self.custom_actions = custom_actions
        self.cores = None

    @property
    def cores(self):
        """Return the number of cores. Example derived attribute, not present in the config file."""
        if self._cores is None:
            # FIXME boto3 call to retrieve the value
            self._cores = "1"
        return self._cores

    @cores.setter
    def cores(self, value):
        self._cores = value