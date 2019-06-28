# Copyright (C) GRyCAP - I3M - UPV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Module with methods and classes to create the function deployment package."""

from zipfile import ZipFile
from io import BytesIO
from scar.providers.aws.udocker import Udocker
from scar.providers.aws.validators import AWSValidator
from scar.exceptions import exception
import scar.logger as logger
from scar.http.request import get_file
from scar.utils import FileUtils, lazy_property, GitHubUtils, \
                       GITHUB_USER, GITHUB_SUPERVISOR_PROJECT


def _download_handler_code(supervisor_version: str, scar_tmp_folder_path: str,
                           handler_name: str) -> None:
    function_handler_dest = FileUtils.join_paths(scar_tmp_folder_path, f"{handler_name}.py")
    supervisor_zip_url = GitHubUtils.get_source_code_url(GITHUB_USER, GITHUB_SUPERVISOR_PROJECT,
                                                         supervisor_version)
    supervisor_zip = get_file(supervisor_zip_url)
    file_path = ""
    with ZipFile(BytesIO(supervisor_zip)) as thezip:
        for file in thezip.namelist():
            if file.endswith("function_handler.py"):
                file_path = FileUtils.join_paths(FileUtils.get_tmp_dir(), file)
                thezip.extract(file, FileUtils.get_tmp_dir())
                break
    FileUtils.copy_file(file_path, function_handler_dest)


class FunctionPackager():
    """Class to manage the deployment package creation."""

    @lazy_property
    def udocker(self):
        """Udocker client"""
        udocker = Udocker(self.aws, self.scar_tmp_folder_path)
        return udocker

    def __init__(self, aws_properties, supervisor_version):
        self.aws = aws_properties
        self.supervisor_version = supervisor_version
        self.scar_tmp_folder = FileUtils.create_tmp_dir()
        self.scar_tmp_folder_path = self.scar_tmp_folder.name
        self.package_args = {}

    @exception(logger)
    def create_zip(self):
        """Creates the lambda function deployment package."""
        self._clean_tmp_folders()
        self._download_hander_file()
        self._manage_udocker_images()
        self._add_init_script()
        self._add_extra_payload()
        self._zip_scar_folder()
        self._check_code_size()
        # self._clean_tmp_folders()

    def _clean_tmp_folders(self):
        FileUtils.delete_file(self.aws.lambdaf.zip_file_path)

    def _download_hander_file(self):
        """Download function handler."""
        _download_handler_code(self.supervisor_version,
                               self.scar_tmp_folder_path,
                               self.aws.lambdaf.name)

    def _manage_udocker_images(self):
        if hasattr(self.aws.lambdaf, "image") and \
           hasattr(self.aws, "s3") and \
           hasattr(self.aws.s3, "deployment_bucket"):
            self.udocker.download_udocker_image()
        if hasattr(self.aws.lambdaf, "image_file"):
            if hasattr(self.aws, "config_path"):
                self.aws.lambdaf.image_file = FileUtils.join_paths(self.aws.config_path,
                                                                   self.aws.lambdaf.image_file)
            self.udocker.prepare_udocker_image()

    def _add_init_script(self):
        if hasattr(self.aws.lambdaf, "init_script"):
            if hasattr(self.aws, "config_path"):
                self.aws.lambdaf.init_script = FileUtils.join_paths(self.aws.config_path,
                                                                    self.aws.lambdaf.init_script)
            init_script_name = "init_script.sh"
            FileUtils.copy_file(self.aws.lambdaf.init_script,
                                FileUtils.join_paths(self.scar_tmp_folder_path, init_script_name))
            self.aws.lambdaf.environment.get['Variables']['INIT_SCRIPT_PATH'] = \
            f"/var/task/{init_script_name}"

    def _add_extra_payload(self):
        if hasattr(self.aws.lambdaf, "extra_payload"):
            logger.info("Adding extra payload from {0}".format(self.aws.lambdaf.extra_payload))
            FileUtils.copy_dir(self.aws.lambdaf.extra_payload, self.scar_tmp_folder_path)
            self.aws.lambdaf.environment['Variables']['EXTRA_PAYLOAD'] = "/var/task"

    def _zip_scar_folder(self):
        FileUtils.zip_folder(self.aws.lambdaf.zip_file_path,
                             self.scar_tmp_folder_path,
                             "Creating function package")

    def _check_code_size(self):
        # Check if the code size fits within the AWS limits
        if hasattr(self.aws, "s3") and hasattr(self.aws.s3, "deployment_bucket"):
            AWSValidator.validate_s3_code_size(self.scar_tmp_folder_path,
                                               self.aws.lambdaf.max_s3_payload_size)
        else:
            AWSValidator.validate_function_code_size(self.scar_tmp_folder_path,
                                                     self.aws.lambdaf.max_payload_size)
