import json
import os
import re

import sys

from l1_driver_resource_info import L1DriverResourceInfo
from l1_handler_base import L1HandlerBase
from glimmerglass_cli_connection import GlimmerglassCliConnection


class GlimmerglassL1Handler(L1HandlerBase):

    def __init__(self, logger):
        self._logger = logger

        self._switch_family = None
        self._blade_family = None
        self._port_family = None
        self._switch_model = None
        self._blade_model = None
        self._port_model = None
        self._blade_name_template = None
        self._port_name_template = None

        self._port_logical_mode = None
        self._custom_port_pairing = {}
        self._mapping_info = {}
        self._switch_size = 0

        self._connection = GlimmerglassCliConnection(self._logger)

    def login(self, address, username, password):
        """
        :param address: str
        :param username: str
        :param password: str
        :return: None
        """
        try:
            with open(os.path.join(os.path.dirname(sys.argv[0]), 'glimmerglass_runtime_configuration.json')) as f:
                o = json.loads(f.read())
        except Exception as e:
            self._logger.warn('Failed to read JSON config file: ' + str(e))
            o = {}

        port = o.get("common_variable", {}).get("connection_port", 10034)

        self._port_logical_mode = o.get("driver_variable", {}).get("port_mode", "physical")

        self._switch_family, self._blade_family, self._port_family = o.get("common_variable", {}).get(
            "resource_family_name",
            ['L1 Optical Switch', 'L1 Optical Switch Blade', 'L1 Optical Switch Port'])
        self._switch_model, self._blade_model, self._port_model = o.get("common_variable", {}).get(
            "resource_model_name",
            ['Glimmerglass', 'Blade Glimmerglass', 'Port Glimmerglass'])
        _, self._blade_name_template, self._port_name_template = o.get("common_variable", {}).get(
            "resource_name",
            ['Unused', 'Blade {address}', 'Port {address}'])

        self._connection.set_resource_address(address)
        self._connection.set_port(port)
        self._connection.set_username(username)
        self._connection.set_password(password)
        self._logger.info('Connection will be to address %s on port %d with username %s' % (address, port, username))

    def logout(self):
        """
        :return: None
        """
        pass

    def get_resource_description(self, address):
        """
        :param address: str
        :return: L1DriverResourceInfo
        """

        device_data = {
            "system_info": self._connection.tl1_command("rtrv-system-info:::{counter};"),
            "port_list": self._connection.tl1_command("RTRV-CFG-FIBER::all:{counter};"),
            "connections_map": self._connection.tl1_command("rtrv-crs-fiber::all:{counter};"),
        }

        size_match = re.search(r"LicensedPortMatrix=(?P<src>\d+)x(?P<dst>\d+)", device_data["system_info"],
                               re.DOTALL)

        if size_match is not None:
            size_dict = size_match.groupdict()

            self._switch_size = int(size_dict["src"]) + int(size_dict["dst"])
        else:
            raise Exception(self.__class__.__name__, "Can't find 'size' parameter!")

        model_info_match = re.search('SerialNumber=(?P<serial>\S+)".*SystemType=(?P<type>\S+)".*"(?P<vendor>\S+):' +
                                     'ChassisType=(?P<model>\S+)".*SoftwareActiveVersion=(?P<version>\S+)"',
                                     device_data["system_info"], re.DOTALL)

        # add chassis info
        if model_info_match is None:
            raise Exception(self.__class__.__name__, "Can't parse model info!")
        model_info_dict = model_info_match.groupdict()

        rv = L1DriverResourceInfo('', address, self._switch_family, self._switch_model,
                                  serial=model_info_dict["serial"])
        rv.set_attribute('Vendor', model_info_dict["vendor"])
        rv.set_attribute('Hardware Type', model_info_dict["type"])
        rv.set_attribute('Version', model_info_dict["version"])
        rv.set_attribute('Model', model_info_dict["model"])

        # get port mappings and port info
        address_prefix = address + "/"
        port_map_list = device_data["connections_map"].split("\n")
        port_list = device_data['port_list'].split("\n")

        if self._port_logical_mode.lower() == "logical":
            logical_port_map = dict()
            for port_data in port_list:
                port_info_match = re.search(r"PORTID=(?P<id>\d+).*PORTNAME=(?P<name>(IN|OUT)\d+)" +
                                            ".*PORTHEALTH=(?P<state>good|bad)", port_data, re.DOTALL)
                if port_info_match is not None:
                    port_info_dict = port_info_match.groupdict()
                    logical_port_id = re.sub('(IN|OUT)', '', port_info_dict["name"])
                    if logical_port_id not in logical_port_map.keys():
                        logical_port_map[logical_port_id] = {}
                    if port_info_dict["state"].lower() == "good":
                        port_state = 0  # "Enable"
                    else:
                        port_state = 1  # "Disable"

                    logical_port_map[logical_port_id]['state'] = port_state

                    if 'in' in port_info_dict["name"].lower():
                        logical_port_map[logical_port_id]['in'] = logical_port_id
                    else:
                        if logical_port_id in self._custom_port_pairing.values():
                            for key, value in self._custom_port_pairing.iteritems():
                                if value == logical_port_id and key in logical_port_map:
                                    logical_port_map[key]['out'] = logical_port_id
                        else:
                            logical_port_map[logical_port_id]['out'] = logical_port_id

            for port_id, port_data in logical_port_map.iteritems():
                if 'in' in port_data and 'out' in port_data:
                    logical_port_map[port_id]['port_address'] = '{0}-{1}'.format(
                        logical_port_map[port_id]['in'],
                        logical_port_map[port_id]['out'])

            for port_data in port_map_list:
                port_map_match = re.search(r"IPORTID=(?P<src_port>\d+).*IPORTNAME=(?P<src_port_name>\S+),IP.*" +
                                           "OPORTID=(?P<dst_port>\d+).*OPORTNAME=(?P<dst_port_name>\S+),OP.*",
                                           port_data, re.DOTALL)
                if port_map_match is not None:
                    port_map_dict = port_map_match.groupdict()
                    src_logical_port_id = re.sub('(IN|OUT)', '', port_map_dict["src_port_name"])
                    dst_logical_port_id = re.sub('(IN|OUT)', '', port_map_dict["dst_port_name"])
                    if src_logical_port_id in logical_port_map.keys() \
                            and dst_logical_port_id in logical_port_map.keys():
                        self._mapping_info[dst_logical_port_id] = src_logical_port_id

            for logical_port_index, logical_port_data in logical_port_map.iteritems():
                if 'port_address' not in logical_port_data:
                    continue

                if logical_port_index in self._mapping_info:
                    map_path = address_prefix + logical_port_map[self._mapping_info[logical_port_index]]['port_address']
                else:
                    map_path = None

                port = L1DriverResourceInfo(self._port_name_template.replace('{address}',
                                                                             str(logical_port_data['port_address'])),
                                            address_prefix + logical_port_data['port_address'],
                                            self._port_family,
                                            self._port_model,
                                            map_path=map_path)
                rv.add_subresource(port)
                port.set_attribute('State', logical_port_data['state'], typename='Lookup')
                port.set_attribute('Protocol Type', 0, typename='Lookup')
                port.set_attribute('Port Description', '')
        else:
            for port_data in port_map_list:
                port_map_match = re.search(r"IPORTID=(?P<src_port>\d+).*IPORTNAME=(?P<src_port_name>\S+),IP.*" +
                                           "OPORTID=(?P<dst_port>\d+).*OPORTNAME=(?P<dst_port_name>\S+),OP.*",
                                           port_data, re.DOTALL)

                if port_map_match is not None:
                    port_map_dict = port_map_match.groupdict()
                    if int(port_map_dict['src_port']) > 0 and int(port_map_dict['dst_port']) > 0:
                        src_port = port_map_dict["src_port"]
                        dst_port = port_map_dict["dst_port"]
                        # self._mapping_info[dst_port] = src_port
                        self._mapping_info[src_port] = dst_port

            for port_data in port_list:
                port_info_match = re.search(r"PORTID=(?P<id>\d+).*PORTNAME=(?P<name>(IN|OUT)\d+)" +
                                            ".*PORTHEALTH=(?P<state>good|bad)", port_data, re.DOTALL)

                if port_info_match is not None:
                    port_info_dict = port_info_match.groupdict()

                    port_id = port_info_dict["id"]
                    # port_resource_info.set_name(port_info_dict["name"])

                    if port_id in self._mapping_info:
                        map_path = address_prefix + self._mapping_info[port_id]
                    else:
                        map_path = None

                    port = L1DriverResourceInfo(self._port_name_template.replace('{address}', str(port_id)),
                                                address_prefix + port_info_dict["id"],
                                                self._port_family,
                                                self._port_model,
                                                map_path=map_path)

                    port.set_attribute('State', 0 if port_info_dict["state"].lower() == "good" else 1,
                                       typename='Lookup')
                    port.set_attribute('Protocol Type', 0, typename='Lookup')
                    port.set_attribute('Port Description', port_info_dict["name"])

                    rv.add_subresource(port)
        return rv

    def map_uni(self, src_port, dst_port):
        """
        :param src_port: str: source port resource full address separated by '/'
        :param dst_port: str: destination port resource full address separated by '/'
        :return: None
        """
        self._logger.info('map_uni {} {}'.format(src_port, dst_port))

        src_port = src_port.split('/')
        dst_port = dst_port.split('/')

        src_in_port = min(int(src_port[1]), int(dst_port[1]))

        dst_out_port = max(int(src_port[1]), int(dst_port[1]))

        if self._port_logical_mode.lower() == "logical":
            src_in_port = str(10000 + int(src_in_port.split('-')[0]))
            dst_out_port = str(20000 + int(dst_out_port.split('-')[1]))

        self._connection.tl1_command("ent-crs-fiber::%s,%s:{counter};" % (src_in_port, dst_out_port))

    def map_bidi(self, src_port, dst_port, mapping_group_name):
        """
        :param src_port: str: source port resource full address separated by '/'
        :param dst_port: str: destination port resource full address separated by '/'
        :param mapping_group_name: str
        :return: None
        """
        self._logger.info('map_bidi {} {} group={}'.format(src_port, dst_port, mapping_group_name))

        src_port = src_port.split('/')
        dst_port = dst_port.split('/')

        if self._port_logical_mode.lower() == "logical":
            source_port = str(src_port[1]).split('-')
            destination_port = str(dst_port[1]).split('-')
            src_in_port = str(10000 + int(source_port[0]))
            dst_in_port = str(10000 + int(destination_port[0]))
            src_out_port = str(20000 + int(source_port[1]))
            dst_out_port = str(20000 + int(destination_port[1]))

            self._connection.tl1_command("ent-crs-fiber::%s&%s,%s&%s:{counter};" % (
                src_in_port, dst_in_port, dst_out_port, src_out_port))
        else:
            raise Exception(self.__class__.__name__,
                            "Bidirectional port mapping could be done only in logical port_mode " +
                            "(current mode: '" + self._port_logical_mode + "'")

    def map_clear_to(self, src_port, dst_port):
        """
        :param src_port: str: source port resource full address separated by '/'
        :param dst_port: str: destination port resource full address separated by '/'
        :return: None
        """
        self._logger.info('map_clear_to {} {}'.format(src_port, dst_port))

        src_port = src_port.split('/')

        src_in_port = src_port[1]
        if self._port_logical_mode.lower() == "logical":
            source_port = src_port[1].split('-')
            src_in_port = str(10000 + int(source_port[0]))

        self._connection.tl1_command("dlt-crs-fiber::%s:{counter};" % src_in_port)

    def map_clear(self, src_port, dst_port):
        """
        :param src_port: str: source port resource full address separated by '/'
        :param dst_port: str: destination port resource full address separated by '/'
        :return: None
        """
        self._logger.info('map_clear {} {}'.format(src_port, dst_port))

        src_port = src_port.split('/')
        dst_port = dst_port.split('/')

        if self._port_logical_mode.lower() == "logical":
            source_port = src_port[1].split('-')
            destination_port = dst_port[1].split('-')
            src_in_port = str(10000 + int(source_port[0]))
            dst_in_port = str(10000 + int(destination_port[0]))

            self._connection.tl1_command("dlt-crs-fiber::%s&%s:{counter};" % (src_in_port, dst_in_port))
        else:
            self.map_clear_to(src_port, dst_port)

    def set_speed_manual(self, src_port, dst_port, speed, duplex):
        """
        :param src_port: str: source port resource full address separated by '/'
        :param dst_port: str: destination port resource full address separated by '/'
        :param speed: str
        :param duplex: str
        :return: None
        """
        self._logger.info('set_speed_manual {} {} {} {}'.format(src_port, dst_port, speed, duplex))

    def set_state_id(self, state_id):
        """
        :param state_id: str
        :return: None
        """
        self._logger.info('set_state_id {}'.format(state_id))

    def get_attribute_value(self, address, attribute_name):
        """
        :param address: str
        :param attribute_name: str
        :return: str
        """
        self._logger.info('get_attribute_value {} {} -> "fakevalue"'.format(address, attribute_name))
        return 'fakevalue'

    def get_state_id(self):
        """
        :return: str
        """
        self._logger.info('get_state_id')
        return '-1'
