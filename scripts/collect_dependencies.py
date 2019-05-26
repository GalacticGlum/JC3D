import click
import logging
import re
import colorama
import copy
import shutil
import hashlib
import tempfile
import json
import time
import datetime
import requests
import zipfile

from enum import IntEnum
from pathlib import Path
from jsonschema import validate as validate_json

def colourize_string(string, colour):
    return '{color_begin}{string}{color_end}'.format(
        string=string,
        color_begin=colour,
        color_end=colorama.Style.RESET_ALL)

def initialize_logger_format(logger):
    """
    Initialize the specified logger with a coloured format.

    """

    # specify colors for different logging levels
    LOG_COLORS = {
        logging.FATAL: colorama.Fore.LIGHTRED_EX,
        logging.ERROR: colorama.Fore.RED,
        logging.WARNING: colorama.Fore.YELLOW,
        logging.DEBUG: colorama.Fore.LIGHTWHITE_EX
    }

    LOG_LEVEL_FORMATS = {
        logging.INFO: '%(message)s'
    }

    class CustomFormatter(logging.Formatter):
        def format(self, record, *args, **kwargs):
            # if the corresponding logger has children, they may receive modified
            # record, so we want to keep it intact
            new_record = copy.copy(record)
            if new_record.levelno in LOG_COLORS:
                # we want levelname to be in different color, so let's modify it
                new_record.levelname = "{color_begin}{level}{color_end}".format(
                    level=new_record.levelname,
                    color_begin=LOG_COLORS[new_record.levelno],
                    color_end=colorama.Style.RESET_ALL,
                )

            original_format = self._style._fmt
            self._style._fmt = LOG_LEVEL_FORMATS.get(record.levelno, original_format)

            # now we can let standart formatting take care of the rest
            result = super(CustomFormatter, self).format(new_record, *args, **kwargs)

            self._style._fmt = original_format
            return result

    handler = logging.StreamHandler()
    handler.setFormatter(CustomFormatter('%(name)s - %(levelname)s: %(message)s'))
    logger.addHandler(handler)

logger = logging.getLogger(__name__)

initialize_logger_format(logger)

DEFAULT_CONTAINER_DIRECTORY_NAME = 'dependencies'

class DependencySourceType(IntEnum):
    Git = 1
    Archive = 2

    @classmethod
    def get_names_for_schema(cls):
        def to_snake_case(name):
            s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', name)
            return re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
        
        return [to_snake_case(value.name) for value in DependencySourceType]

    @classmethod
    def from_snake_case_name(cls, name):
        name = ''.join(x.capitalize() or '_' for x in name.split('_'))
        return cls[name]

class UnsupportedSourceTypeError(Exception):
    """
    Raised when the source type of a dependency is not supported.

    """

    def __init__(self, source_type):
        super(UnsupportedSourceTypeError, self).__init__(f'Unsupported source type: \'{source_type.name}\'')

class Dependency(object):
    """
    Data class that stores information about a specific dependency.
    
    """

    def __init__(self, name, source_url, source_url_type):
        self.name = name
        self.source_url = source_url
        self.source_url_type = source_url_type

    def process(self, container_directory, force=False):
        """
        Processes the dependency.

        """
        
        destination_path = Path(container_directory) / self.name
        colourized_name = colourize_string(self.name, colorama.Fore.LIGHTWHITE_EX)

        # The lock file contains a hash of the Dependency object that was used to download
        # the contents of the folder. If the hash in the lock file is not the same as the
        # current one, the dependency is regathered.
        lock_filepath = destination_path / 'dependency.lock'
        dependency_hash = self.get_hash()

        if destination_path.is_dir():
            if not force:
                if lock_filepath.is_file():
                    # The lock file is stored as JSON
                    lock_data = json.load(lock_filepath.open())
                    if lock_data.get('dependency_hash') == dependency_hash:
                        logger.info(f'{colourized_name} - Skipped: dependency already installed')
                        return

            shutil.rmtree(destination_path)

        if destination_path.is_dir():
            logger.warning(f'''shutil.rmtree - Waiting for \'{destination_path}\' to be removed...''')
            # The destination path has yet to be deleted. Wait, at most, 10 seconds.
            timeout_time = time.time() + 10
            while time.time() <= timeout_time:
                if not destination_path.is_dir():
                    break

        # Create the destination directory if it does not exist
        destination_path.mkdir(parents=True, exist_ok=True)

        # Delete the lock file
        if lock_filepath.is_file():
            lock_filepath.unlink()

        # Get the source
        if self.source_url_type == DependencySourceType.Git:
            # TODO: Implement git dependencies.
            raise UnsupportedSourceTypeError(DependencySourceType.Git)
        elif self.source_url_type == DependencySourceType.Archive:
            # Extract and build filesystem
            with tempfile.NamedTemporaryFile(delete=False) as tmp_file_handle:
                logger.info(f'{colourized_name} - Downloading archive ({self.source_url})')

                start_time = time.time()
                response = requests.get(self.source_url, stream=True)
                total_length = response.headers.get('content-length')

                # no content length header
                if total_length is None:
                    tmp_file_handle.write(response.content)
                else:
                    total_length = int(total_length)
                    with click.progressbar(length=total_length, label='Downloading...') as bar:
                        for chunk in response.iter_content(chunk_size=4096):
                            tmp_file_handle.write(chunk)
                            bar.update(len(chunk))

            try:
                if not zipfile.is_zipfile(tmp_file_handle.name):
                    raise zipfile.BadZipFile()
            except:
                logger.exception(f'Invalid archive file provided for \'{self.name}\' dependency.')
                return

            logger.info(f'{colourized_name} - Extracting archive')
            with zipfile.ZipFile(tmp_file_handle.name) as zip_file:
                with click.progressbar(zip_file.namelist(), label='Extracting...') as bar:
                    for name in bar:
                        zip_file.extract(name, destination_path)

        # Create a new updated lock file
        json.dump({'dependency_hash': dependency_hash}, lock_filepath.open('w+'))

        # Delete temporary file
        tmp_file_path = Path(tmp_file_handle.name)
        if tmp_file_path.is_file():
            tmp_file_path.unlink()

    def get_hash(self):
        return hashlib.md5(json.dumps({
            'source_url': self.source_url,
            'source_url_type': self.source_url_type
        }, sort_keys=True).encode('utf-8')).hexdigest()

    def __str__(self): return str((self.name, str(self.source_url_type), self.source_url))
    def __repr__(self): return self.__str__()

def find_dependencies_config(directory):
    """
    Finds the dependencies.json in the specified directory.

    :param directory:
        The directory to search for dependencies.json.
    :returns:
        A `pathlib.Path` object pointing to the dependencies.json file or `None`

    """

    path = Path(directory, 'dependencies').with_suffix('.json')
    return path if path.is_file() else None

def process_directory(directory, force):
    dependencies_config = find_dependencies_config(directory)
    if dependencies_config == None:
        logger.error(f'Could not find \'dependencies.json\' file in {directory}.')
        return None

    DEPENDENCIES_CONFIG_SCHEMA = {
        'type': 'object',
        'properties': {
            'subdirectories': {
                'type': 'array',
                'items': {
                    'type': 'string'
                }
            },
            'container_directory_name': {
                'type': 'string'
            },
            'dependencies': {
                'type': 'object'
            }
        }
    }

    DEPENDENCY_SCHEMA = {
        'type': 'object',
        'properties': {
            'url': {
                'type': 'string',
                'format': 'uri'
            },
            'url_type': {
                'type': 'string',
                'enum': DependencySourceType.get_names_for_schema()
            }
        },
        'required': ['url', 'url_type']
    }
    
    with open(dependencies_config.absolute(), 'r') as dependencies_file:
        json_data = json.load(dependencies_file)
        
        try:
            validate_json(instance=json_data, schema=DEPENDENCIES_CONFIG_SCHEMA)
        except:
            logger.exception(f'Invalid dependencies.json file (\'{dependencies_config.absolute()}\').')
            exit(-1)

        if 'dependencies' in json_data:
            dependencies = json_data['dependencies']

            container_directory_name = json_data.get('container_directory_name', DEFAULT_CONTAINER_DIRECTORY_NAME)
            container_directory = Path(directory) / container_directory_name

            # Process the dependencies
            for dependency_name in dependencies:
                try:
                    validate_json(instance=dependencies[dependency_name], schema=DEPENDENCY_SCHEMA)
                except:
                    logger.exception(f'Invalid dependency in \'{dependencies_config.absolute()}\' with name \'{dependency_name}\'')
                    continue

                source_url = dependencies[dependency_name]['url']
                source_url_type = DependencySourceType.from_snake_case_name(dependencies[dependency_name]['url_type'])
                dependency = Dependency(dependency_name, source_url, source_url_type)

                dependency.process(container_directory, force)

        if 'subdirectories' in json_data:
            subdirectories = json_data['subdirectories']
            for subdirectory in subdirectories:
                process_directory(Path(subdirectory).resolve(), force)

def _set_level(ctx, param, value):
    x = getattr(logging, value.upper(), None)
    if x is None:
        raise click.BadParameter(f'Must be CRITICAL, ERROR, WARNING, INFO or DEBUG, not \'{value}\'')
    
    logger.setLevel(x)

@click.command()
@click.option('--force', '-f', is_flag=True, default=False, help='Cleans all existing dependencies and regathers them.')
@click.option('--verbosity', '-v', default='INFO', help='Either CRITICAL, ERROR, WARNING, INFO, or DEBUG.', callback=_set_level)
def cli(force, verbosity):
    """
    Collects and processes the dependencies specified in the 'dependencies.json' file.
    
    """

    working_directory = Path().absolute()
    process_directory(working_directory, force)
