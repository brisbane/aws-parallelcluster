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
import pytest

from pcluster.models.common import Param
from pcluster.utils import InstanceTypeInfo
from pcluster.validators.cluster_validators import (
    FSX_MESSAGES,
    FSX_SUPPORTED_ARCHITECTURES_OSES,
    ArchitectureOsValidator,
    ComputeResourceSizeValidator,
    DcvValidator,
    DuplicateInstanceTypeValidator,
    DuplicateMountDirValidator,
    EfaOsArchitectureValidator,
    EfaPlacementGroupValidator,
    EfaSecurityGroupValidator,
    EfaValidator,
    FsxArchitectureOsValidator,
    FsxNetworkingValidator,
    InstanceArchitectureCompatibilityValidator,
    NumberOfStorageValidator,
    QueueNameValidator,
    SchedulerOsValidator,
    SimultaneousMultithreadingArchitectureValidator,
    TagKeyValidator,
)
from tests.common import MockedBoto3Request
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.validators.cluster_validators.boto3"


@pytest.mark.parametrize(
    "os, scheduler, expected_message",
    [
        ("centos7", "slurm", None),
        ("centos8", "slurm", None),
        ("ubuntu1804", "slurm", None),
        ("alinux2", "slurm", None),
        ("centos7", "awsbatch", "scheduler supports the following Operating Systems"),
        ("centos8", "awsbatch", "scheduler supports the following Operating Systems"),
        ("ubuntu1804", "awsbatch", "scheduler supports the following Operating Systems"),
        ("alinux2", "awsbatch", None),
    ],
)
def test_scheduler_os_validator(os, scheduler, expected_message):
    actual_failures = SchedulerOsValidator().execute(Param(os), Param(scheduler))
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "min_count, max_count, expected_message",
    [
        (1, 2, None),
        (1, 1, None),
        (2, 1, "Max count must be greater than or equal to min count"),
    ],
)
def test_compute_resource_size_validator(min_count, max_count, expected_message):
    actual_failures = ComputeResourceSizeValidator().execute(Param(min_count), Param(max_count))
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "instance_type_list, expected_message",
    [
        (["i1"], None),
        (["i1", "i2"], None),
        (["i1", "i2", "i3"], None),
        (["i1", "i1", "i2"], "Instance type i1 cannot be specified for multiple Compute Resources"),
        (
            ["i1", "i2", "i3", "i2", "i1"],
            "Instance types i2, i1 cannot be specified for multiple Compute Resources",
        ),
    ],
)
def test_duplicate_instance_type_validator(instance_type_list, expected_message):
    instance_type_param_list = [Param(instance_type) for instance_type in instance_type_list]
    actual_failures = DuplicateInstanceTypeValidator().execute(instance_type_param_list)
    assert_failure_messages(actual_failures, expected_message)


# ---------------- EFA validators ---------------- #


@pytest.mark.parametrize(
    "instance_type, efa_enabled, gdr_support, efa_supported, expected_message",
    [
        # EFAGDR without EFA
        ("c5n.18xlarge", False, True, True, "GDR Support can be used only if EFA is enabled"),
        # EFAGDR with EFA
        ("c5n.18xlarge", True, True, True, None),
        # EFA without EFAGDR
        ("c5n.18xlarge", True, False, True, None),
        # Unsupported instance type
        ("t2.large", True, False, False, "does not support EFA"),
        ("t2.large", False, False, False, None),
    ],
)
def test_efa_validator(mocker, boto3_stubber, instance_type, efa_enabled, gdr_support, efa_supported, expected_message):
    if efa_enabled:
        mocker.patch(
            "pcluster.validators.cluster_validators.InstanceTypeInfo.init_from_instance_type",
            return_value=InstanceTypeInfo(
                {
                    "InstanceType": instance_type,
                    "VCpuInfo": {"DefaultVCpus": 4, "DefaultCores": 2},
                    "NetworkInfo": {"EfaSupported": instance_type == "c5n.18xlarge"},
                }
            ),
        )

    actual_failures = EfaValidator().execute(Param(instance_type), Param(efa_enabled), Param(gdr_support))
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "efa_enabled, placement_group_id, placement_group_enabled, expected_message",
    [
        # Efa disabled, no check on placement group configuration
        (False, None, False, None),
        # Efa enabled
        (True, None, False, "You may see better performance using a Placement Group"),
        (True, None, True, None),
        (True, "existing_pg", False, None),
    ],
)
def test_efa_placement_group_validator(efa_enabled, placement_group_id, placement_group_enabled, expected_message):
    actual_failures = EfaPlacementGroupValidator().execute(
        Param(efa_enabled), Param(placement_group_id), Param(placement_group_enabled)
    )
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "efa_enabled, security_groups, additional_security_groups, ip_permissions, ip_permissions_egress, expected_message",
    [
        # Efa disabled, no checks on security groups
        (False, [], [], [], [], None),
        # Efa enabled, if not specified SG will be created by the cluster
        (True, [], [], [], [], None),
        (True, [], ["sg-12345678"], [{"IpProtocol": "-1", "UserIdGroupPairs": []}], [], None),
        # Inbound rules only
        (
            True,
            ["sg-12345678"],
            [],
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            [],
            "security group that allows all inbound and outbound",
        ),
        # right sg
        (
            True,
            ["sg-12345678"],
            [],
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            None,
        ),
        # Multiple sec groups, one right
        (
            True,
            ["sg-23456789", "sg-12345678"],
            [],
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            None,
        ),
        # Multiple sec groups, no one right
        (True, ["sg-23456789", "sg-34567890"], [], [], [], "security group that allows all inbound and outbound"),
        # Wrong rules
        (
            True,
            ["sg-12345678"],
            [],
            [
                {
                    "PrefixListIds": [],
                    "FromPort": 22,
                    "IpRanges": [{"CidrIp": "203.0.113.0/24"}],
                    "ToPort": 22,
                    "IpProtocol": "tcp",
                    "UserIdGroupPairs": [],
                }
            ],
            [],
            "security group that allows all inbound and outbound",
        ),
        # Right SG specified as additional sg
        (
            True,
            ["sg-23456789"],
            ["sg-12345678"],
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            None,
        ),
    ],
)
def test_efa_security_group_validator(
    boto3_stubber,
    efa_enabled,
    security_groups,
    additional_security_groups,
    ip_permissions,
    ip_permissions_egress,
    expected_message,
):
    def _append_mocked_describe_sg_request(ip_perm, ip_perm_egress, sec_group):
        describe_security_groups_response = {
            "SecurityGroups": [
                {
                    "IpPermissionsEgress": ip_perm_egress,
                    "Description": "My security group",
                    "IpPermissions": ip_perm,
                    "GroupName": "MySecurityGroup",
                    "OwnerId": "123456789012",
                    "GroupId": sec_group,
                }
            ]
        }
        return MockedBoto3Request(
            method="describe_security_groups",
            response=describe_security_groups_response,
            expected_params={"GroupIds": [security_group]},
        )

    if efa_enabled:
        # Set SG different by sg-12345678 as incomplete. The only full valid SG can be the sg-12345678 one.
        perm = ip_permissions if "sg-12345678" else []
        perm_egress = ip_permissions_egress if "sg-12345678" else []

        mocked_requests = []
        if security_groups:
            for security_group in security_groups:
                mocked_requests.append(_append_mocked_describe_sg_request(perm, perm_egress, security_group))

            # We don't need to check additional sg only if security_group is not a custom one.
            if additional_security_groups:
                for security_group in additional_security_groups:
                    mocked_requests.append(_append_mocked_describe_sg_request(perm, perm_egress, security_group))

        boto3_stubber("ec2", mocked_requests)

    actual_failures = EfaSecurityGroupValidator().execute(
        Param(efa_enabled), Param(security_groups), Param(additional_security_groups)
    )
    assert_failure_messages(actual_failures, expected_message)


# ---------------- Architecture Validators ---------------- #


@pytest.mark.parametrize(
    "simultaneous_multithreading, architecture, expected_message",
    [
        (True, "x86_64", None),
        (False, "x86_64", None),
        (
            True,
            "arm64",
            "Simultaneous Multithreading is only supported on instance types that support these architectures",
        ),
        (False, "arm64", None),
    ],
)
def test_simultaneous_multithreading_architecture_validator(
    simultaneous_multithreading, architecture, expected_message
):
    actual_failures = SimultaneousMultithreadingArchitectureValidator().execute(
        Param(simultaneous_multithreading), architecture
    )
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "efa_enabled, os, architecture, expected_message",
    [
        (True, "alinux2", "x86_64", None),
        (True, "alinux2", "arm64", None),
        (True, "centos8", "x86_64", None),
        (
            True,
            "centos8",
            "arm64",
            "EFA currently not supported on centos8 for arm64 architecture",
        ),
        (False, "centos8", "arm64", None),
        (True, "ubuntu1804", "x86_64", None),
        (True, "ubuntu1804", "arm64", None),
    ],
)
def test_efa_os_architecture_validator(efa_enabled, os, architecture, expected_message):
    actual_failures = EfaOsArchitectureValidator().execute(Param(efa_enabled), Param(os), architecture)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "os, architecture, expected_message",
    [
        # All OSes supported for x86_64
        ("alinux", "x86_64", None),
        ("alinux2", "x86_64", None),
        ("centos7", "x86_64", None),
        ("centos8", "x86_64", None),
        ("ubuntu1604", "x86_64", None),
        ("ubuntu1804", "x86_64", None),
        # Only a subset of OSes supported for arm64
        ("alinux", "arm64", "arm64 is only supported for the following operating systems"),
        ("alinux2", "arm64", None),
        ("centos7", "arm64", "arm64 is only supported for the following operating systems"),
        ("centos8", "arm64", None),
        ("ubuntu1604", "arm64", "arm64 is only supported for the following operating systems"),
        ("ubuntu1804", "arm64", None),
    ],
)
def test_architecture_os_validator(os, architecture, expected_message):
    """Verify that the correct set of OSes is supported for each supported architecture."""
    actual_failures = ArchitectureOsValidator().execute(Param(os), architecture)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "head_node_architecture, compute_architecture, compute_instance_type, expected_message",
    [
        ("x86_64", "x86_64", "c5.xlarge", None),
        (
            "x86_64",
            "arm64",
            "m6g.xlarge",
            "none of which are compatible with the architecture supported by the head node instance type",
        ),
        (
            "arm64",
            "x86_64",
            "c5.xlarge",
            "none of which are compatible with the architecture supported by the head node instance type",
        ),
        ("arm64", "arm64", "m6g.xlarge", None),
    ],
)
def test_instance_architecture_compatibility_validator(
    mocker, head_node_architecture, compute_architecture, compute_instance_type, expected_message
):
    mocker.patch(
        "pcluster.validators.cluster_validators.get_supported_architectures_for_instance_type",
        return_value=[compute_architecture],
    )
    actual_failures = InstanceArchitectureCompatibilityValidator().execute(
        Param(compute_instance_type), head_node_architecture
    )
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "name, expected_message",
    [
        ("default", "forbidden"),
        ("1queue", "must begin with a letter"),
        ("queue_1", "only contain lowercase letters, digits and hyphens"),
        ("aQUEUEa", "only contain lowercase letters, digits and hyphens"),
        ("queue1!2", "only contain lowercase letters, digits and hyphens"),
        ("my-default-queue2", None),
        ("queue-123456789abcdefghijklmnop", "can be at most 30 chars long"),
        ("queue-123456789abcdefghijklmno", None),
    ],
)
def test_queue_name_validator(name, expected_message):
    actual_failures = QueueNameValidator().execute(Param(name))
    assert_failure_messages(actual_failures, expected_message)


# -------------- Storage validators -------------- #


@pytest.mark.parametrize(
    "fsx_vpc, ip_permissions, network_interfaces, expected_message",
    [
        (  # working case, right vpc and sg, multiple network interfaces
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            ["eni-09b9460295ddd4e5f", "eni-001b3cef7c78b45c4"],
            None,
        ),
        (  # working case, right vpc and sg, single network interface
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            ["eni-09b9460295ddd4e5f"],
            None,
        ),
        (  # not working case --> no network interfaces
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            [],
            "doesn't have Elastic Network Interfaces attached",
        ),
        (  # not working case --> wrong vpc
            "vpc-06e4ab6c6ccWRONG",
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            ["eni-09b9460295ddd4e5f"],
            "only support using FSx file system that is in the same VPC as the stack",
        ),
        (  # not working case --> wrong ip permissions in security group
            "vpc-06e4ab6c6cWRONG",
            [
                {
                    "PrefixListIds": [],
                    "FromPort": 22,
                    "IpRanges": [{"CidrIp": "203.0.113.0/24"}],
                    "ToPort": 22,
                    "IpProtocol": "tcp",
                    "UserIdGroupPairs": [],
                }
            ],
            ["eni-09b9460295ddd4e5f"],
            [
                "only support using FSx file system that is in the same VPC as the stack",
                "does not satisfy mounting requirement",
            ],
        ),
    ],
)
def test_fsx_network_validator(boto3_stubber, fsx_vpc, ip_permissions, network_interfaces, expected_message):
    describe_file_systems_response = {
        "FileSystems": [
            {
                "VpcId": fsx_vpc,
                "NetworkInterfaceIds": network_interfaces,
                "SubnetIds": ["subnet-12345678"],
                "FileSystemType": "LUSTRE",
                "CreationTime": 1567636453.038,
                "ResourceARN": "arn:aws:fsx:us-west-2:111122223333:file-system/fs-0ff8da96d57f3b4e3",
                "StorageCapacity": 3600,
                "LustreConfiguration": {"WeeklyMaintenanceStartTime": "4:07:00"},
                "FileSystemId": "fs-0ff8da96d57f3b4e3",
                "DNSName": "fs-0ff8da96d57f3b4e3.fsx.us-west-2.amazonaws.com",
                "OwnerId": "059623208481",
                "Lifecycle": "AVAILABLE",
            }
        ]
    }
    fsx_mocked_requests = [
        MockedBoto3Request(
            method="describe_file_systems",
            response=describe_file_systems_response,
            expected_params={"FileSystemIds": ["fs-0ff8da96d57f3b4e3"]},
        )
    ]
    boto3_stubber("fsx", fsx_mocked_requests)

    describe_subnets_response = {
        "Subnets": [
            {
                "AvailabilityZone": "us-east-2c",
                "AvailabilityZoneId": "use2-az3",
                "AvailableIpAddressCount": 248,
                "CidrBlock": "10.0.1.0/24",
                "DefaultForAz": False,
                "MapPublicIpOnLaunch": False,
                "State": "available",
                "SubnetId": "subnet-12345678",
                "VpcId": "vpc-06e4ab6c6cEXAMPLE",
                "OwnerId": "111122223333",
                "AssignIpv6AddressOnCreation": False,
                "Ipv6CidrBlockAssociationSet": [],
                "Tags": [{"Key": "Name", "Value": "MySubnet"}],
                "SubnetArn": "arn:aws:ec2:us-east-2:111122223333:subnet/subnet-12345678",
            }
        ]
    }
    ec2_mocked_requests = [
        MockedBoto3Request(
            method="describe_subnets",
            response=describe_subnets_response,
            expected_params={"SubnetIds": ["subnet-12345678"]},
        )
    ]

    if network_interfaces:
        network_interfaces_in_response = []
        for network_interface in network_interfaces:
            network_interfaces_in_response.append(
                {
                    "Association": {
                        "AllocationId": "eipalloc-01564b674a1a88a47",
                        "AssociationId": "eipassoc-02726ee370e175cea",
                        "IpOwnerId": "111122223333",
                        "PublicDnsName": "ec2-34-248-114-123.eu-west-1.compute.amazonaws.com",
                        "PublicIp": "34.248.114.123",
                    },
                    "Attachment": {
                        "AttachmentId": "ela-attach-0cf98331",
                        "DeleteOnTermination": False,
                        "DeviceIndex": 1,
                        "InstanceOwnerId": "amazon-aws",
                        "Status": "attached",
                    },
                    "AvailabilityZone": "eu-west-1a",
                    "Description": "Interface for NAT Gateway nat-0a8b0e0d28266841f",
                    "Groups": [{"GroupName": "default", "GroupId": "sg-12345678"}],
                    "InterfaceType": "nat_gateway",
                    "Ipv6Addresses": [],
                    "MacAddress": "0a:e5:8a:82:fd:24",
                    "NetworkInterfaceId": network_interface,
                    "OwnerId": "111122223333",
                    "PrivateDnsName": "ip-10-0-124-85.eu-west-1.compute.internal",
                    "PrivateIpAddress": "10.0.124.85",
                    "PrivateIpAddresses": [
                        {
                            "Association": {
                                "AllocationId": "eipalloc-01564b674a1a88a47",
                                "AssociationId": "eipassoc-02726ee370e175cea",
                                "IpOwnerId": "111122223333",
                                "PublicDnsName": "ec2-34-248-114-123.eu-west-1.compute.amazonaws.com",
                                "PublicIp": "34.248.114.123",
                            },
                            "Primary": True,
                            "PrivateDnsName": "ip-10-0-124-85.eu-west-1.compute.internal",
                            "PrivateIpAddress": "10.0.124.85",
                        }
                    ],
                    "RequesterId": "036872051663",
                    "RequesterManaged": True,
                    "SourceDestCheck": False,
                    "Status": "in-use",
                    "SubnetId": "subnet-12345678",
                    "TagSet": [],
                    "VpcId": fsx_vpc,
                }
            )
        describe_network_interfaces_response = {"NetworkInterfaces": network_interfaces_in_response}
        ec2_mocked_requests.append(
            MockedBoto3Request(
                method="describe_network_interfaces",
                response=describe_network_interfaces_response,
                expected_params={"NetworkInterfaceIds": network_interfaces},
            )
        )

        if fsx_vpc == "vpc-06e4ab6c6cEXAMPLE":
            # the describe security group is performed only if the VPC of the network interface is the same of the FSX
            describe_security_groups_response = {
                "SecurityGroups": [
                    {
                        "IpPermissionsEgress": ip_permissions,
                        "Description": "My security group",
                        "IpPermissions": ip_permissions,
                        "GroupName": "MySecurityGroup",
                        "OwnerId": "123456789012",
                        "GroupId": "sg-12345678",
                    }
                ]
            }
            ec2_mocked_requests.append(
                MockedBoto3Request(
                    method="describe_security_groups",
                    response=describe_security_groups_response,
                    expected_params={"GroupIds": ["sg-12345678"]},
                )
            )

    boto3_stubber("ec2", ec2_mocked_requests)

    actual_failures = FsxNetworkingValidator().execute(Param("fs-0ff8da96d57f3b4e3"), Param("subnet-12345678"))
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "architecture, os, expected_message",
    [
        # Supported combinations
        ("x86_64", "alinux", None),
        ("x86_64", "alinux2", None),
        ("x86_64", "centos7", None),
        ("x86_64", "centos8", None),
        ("x86_64", "ubuntu1604", None),
        ("x86_64", "ubuntu1804", None),
        ("arm64", "ubuntu1804", None),
        ("arm64", "alinux2", None),
        ("arm64", "centos8", None),
        # Unsupported combinations
        (
            "UnsupportedArchitecture",
            "alinux2",
            FSX_MESSAGES["errors"]["unsupported_architecture"].format(
                supported_architectures=list(FSX_SUPPORTED_ARCHITECTURES_OSES.keys())
            ),
        ),
        (
            "arm64",
            "centos7",
            FSX_MESSAGES["errors"]["unsupported_os"].format(
                architecture="arm64", supported_oses=FSX_SUPPORTED_ARCHITECTURES_OSES.get("arm64")
            ),
        ),
        (
            "arm64",
            "alinux",
            FSX_MESSAGES["errors"]["unsupported_os"].format(
                architecture="arm64", supported_oses=FSX_SUPPORTED_ARCHITECTURES_OSES.get("arm64")
            ),
        ),
        (
            "arm64",
            "ubuntu1604",
            FSX_MESSAGES["errors"]["unsupported_os"].format(
                architecture="arm64", supported_oses=FSX_SUPPORTED_ARCHITECTURES_OSES.get("arm64")
            ),
        ),
    ],
)
def test_fsx_architecture_os_validator(architecture, os, expected_message):
    actual_failures = FsxArchitectureOsValidator().execute(architecture, Param(os))
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "mount_dir_list, expected_message",
    [
        (
            ["dir1"],
            None,
        ),
        (
            ["dir1", "dir2"],
            None,
        ),
        (
            ["dir1", "dir2", "dir3"],
            None,
        ),
        (
            ["dir1", "dir1", "dir2"],
            "Mount directory dir1 cannot be specified for multiple volumes",
        ),
        (
            ["dir1", "dir2", "dir3", "dir2", "dir1"],
            "Mount directories dir2, dir1 cannot be specified for multiple volumes",
        ),
    ],
)
def test_duplicate_mount_dir_validator(mount_dir_list, expected_message):
    mount_dir_param_list = [Param(mount_dir) for mount_dir in mount_dir_list]
    actual_failures = DuplicateMountDirValidator().execute(mount_dir_param_list)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "storage_type, max_number, storage_count, expected_message",
    [
        ("fsx", 1, 0, None),
        ("efs", 1, 1, None),
        ("ebs", 5, 6, "Invalid number of shared storage of ebs type specified. Currently only supports upto 5"),
    ],
)
def test_number_of_storage_validator(storage_type, max_number, storage_count, expected_message):
    actual_failures = NumberOfStorageValidator().execute(storage_type, max_number, storage_count)
    assert_failure_messages(actual_failures, expected_message)


# -------------- Third party software validators -------------- #


@pytest.mark.parametrize(
    "dcv_enabled, os, instance_type, allowed_ips, port, expected_message",
    [
        (True, "alinux", "t2.medium", None, None, "Please double check the Os configuration parameter"),
        (False, "alinux", "t2.medium", None, None, None),  # doesn't fail because DCV is disabled
        (True, "centos7", "t2.medium", None, None, None),
        (True, "centos8", "t2.medium", None, None, None),
        (True, "ubuntu1804", "t2.medium", None, None, None),
        (True, "ubuntu1804", "t2.medium", None, "1.2.3.4/32", None),
        (True, "centos7", "t2.medium", "0.0.0.0/0", 8443, "port 8443 to the world"),
        (True, "centos8", "t2.medium", "0.0.0.0/0", 9090, "port 9090 to the world"),
        (True, "alinux2", "t2.medium", None, None, None),
        (True, "alinux2", "t2.nano", None, None, "is recommended to use an instance type with at least"),
        (True, "alinux2", "t2.micro", None, None, "is recommended to use an instance type with at least"),
        (False, "alinux2", "t2.micro", None, None, None),  # doesn't fail because DCV is disabled
        (True, "ubuntu1804", "m6g.xlarge", None, None, None),
        (True, "alinux2", "m6g.xlarge", None, None, None),
        (True, "centos7", "m6g.xlarge", None, None, "Please double check the Os configuration parameter"),
        (True, "centos8", "m6g.xlarge", None, None, None),
    ],
)
def test_dcv_validator(dcv_enabled, os, instance_type, allowed_ips, port, expected_message):
    actual_failures = DcvValidator().execute(
        Param(instance_type),
        Param(dcv_enabled),
        Param(allowed_ips),
        Param(port),
        Param(os),
        "x86_64" if instance_type.startswith("t2") else "arm64",
    )
    assert_failure_messages(actual_failures, expected_message)


# -------------- Other validators -------------- #


@pytest.mark.parametrize(
    "key, expected_message",
    [
        ("key1", None),
        ("Version", "The tag key 'Version' is a reserved one"),
    ],
)
def test_tags_validator(key, expected_message):
    actual_failures = TagKeyValidator().execute(Param(key))
    assert_failure_messages(actual_failures, expected_message)