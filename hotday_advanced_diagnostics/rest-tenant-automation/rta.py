# -*- coding: utf-8 -*-
# Required Libraries.
import copy
import csv
import datetime
import json
import logging
import os
import re
import sys
import time
import traceback
import paramiko
import lib.helper

import boto3
import requests
from botocore.exceptions import ClientError

"""
Declaration of Static Variables
"""
key_tenantId = 'tenantId'
key_skip = 'skip'
key_tenantLogin = 'tenantLogin'
key_tenantPassword = 'tenantPassword'
key_tenantUrl = 'tenantUrl'
key_tenantToken = 'tenantToken'
key_firstName = 'firstName'
key_lastName = 'lastName'
key_groupId = 'groupId'
key_email = 'email'
key_id = 'id'
key_publicDnsName = 'publicDnsName'
key_publicIpAddress = 'publicIpAddress'
key_isClusterAdminGroup = 'isClusterAdminGroup'
key_sshUser = 'sshUser'
key_sshPassword = 'sshPassword'

regex_valid_chars = "^[A-Za-z0-9\s\._-]*$"

API_EP_CM_TENANTCONFIGS = "/api/v1.0/control/tenantManagement/tenantConfigs/?active=true"
API_EP_CM_GROUPS = "/api/v1.0/onpremise/groups/"
API_EP_CM_USERS = "/api/v1.0/onpremise/users/"
API_EP_CM_CREATE_TENANT = "/api/v1.0/control/tenantManagement/createTenant/"
API_EP_CM_DEACTIVATE_TENANT = "/api/v1.0/control/tenantManagement/deactivateTenant/"
API_EP_CM_REMOVE_TENANT = "/api/v1.0/control/tenantManagement/removeTenant/"
API_EP_CM_CREATETOKEN_TENANT = "/api/v1.0/control/tenantManagement/tokens/"

API_EP_TENANT_SVC_DETECTION_RULES = "/api/config/v1/service/detectionRules/"
API_EP_TENANT_DASHBOARDS = "/api/config/v1/dashboards/"
API_EP_TENANT_APP = "/api/config/v1/applications/web/"
API_EP_TENANT_REQUESTATTRIBUTES = "/api/config/v1/service/requestAttributes/"
API_EP_TENANT_AUTOTAGGING = "/api/config/v1/autoTags/"
API_EP_TENANT_MANAGEMENTZONES = "/api/config/v1/managementZones/"
API_EP_TENANT_APPDETECTION_RULES = "/api/config/v1/applicationDetectionRules/"
API_EP_TENANT_DEFAULTAPP = API_EP_TENANT_APP + "default"
API_EP_TENANT_MONITOR = "/api/v1/synthetic/monitors/"
API_EP_TENANT_FREQUENTISSUE = "/api/config/v1/frequentIssueDetection/"

API_EASYTRAVEL_PLUGIN = ":8091/services/ConfigurationService/setPluginEnabled?name="
API_EASYTRAVEL_PING = ":1697/ping"

CSV_DATA = {}
# Read Configuration and assign the variables
config = json.load(open('config.json'))

CSV_DIR = config['csv_dir']
CSV_TEMP_DIR = CSV_DIR + '/temp'
CSV_FILE = config['csv_file']
LOG_FILE = config['log_file']
LOG_DIR = config['log_dir']
DATA_DIR = "data"
CMC_URL = config['cmc']['cmc_url']

# Actions Control
ACTION_CREATE_TENANT = config['action_create']['create_tenant']
ACTION_SET_UP_ENV = config['action_create']['set_up_env']
ACTION_CREATE_USERGROUP = config['action_create']['create_user_group']
ACTION_CREATE_USER = config['action_create']['create_user']
ACTION_CREATE_ALLINONETOKEN = config['action_create']['create_allinone_token']
ACTION_CREATE_EC2INSTANCE = config['action_create']['create_ec2_instance']
ACTION_FETCH_EC2INSTANCE = config['action_create']['fetch_ec2_instance']
ACTION_DEACTIVATE_TENANT = config['action_remove']['deactivate_tenant']
ACTION_REMOVE_TENANT = config['action_remove']['remove_tenant']
ACTION_DELETE_USERGROUP = config['action_remove']['delete_user_group']
ACTION_DELETE_USER = config['action_remove']['delete_user']
ACTION_DELETE_EC2INSTANCE = config['action_remove']['delete_ec2_instance']
ACTION_TEST_SSH_CONNECTION = config['action_test']['ssh_connection']
ACTION_TEST_ET_PING = config['action_test']['easytravel_ping']
ACTION_TEST_TENANT_API = config['action_test']['tenant_api']

'''
{CMC_URL}/debugui/debug/tokenviewernew?
For creating tokens for all the environments, go to the debug ui of the CMC environment,
check all checkboxes and action_create a new token.
'''
CMC_TOKEN = config['cmc']['cmc_token']

AWS_USERDATA_FILE = config['aws']['aws_dir'] + '/' + config['aws']['user_data']

SKEL_TENANT = json.load(open('skel/tenant.json', 'r'))
SKEL_TXT_DASHBOARD = (open('skel/dashboard.json', 'r', encoding='utf8')).read()
SKEL_TXT_MONITOR = (open('skel/monitor.json', 'r', encoding='utf8')).read()
SKEL_DEFAULTAPP = json.load(open('skel/defaultapp.json', 'r'))
SKEL_GROUP = json.load(open('skel/group.json', 'r'))
SKEL_USER = json.load(open('skel/user.json', 'r'))
SKEL_TOKEN = json.load(open('skel/allinonetoken.json', 'r'))

SKEL_APPLICATION1 = json.load(open('skel/easytravel/application-1.json', 'r'))
SKEL_APPLICATION2 = json.load(open('skel/easytravel/application-2.json', 'r'))
SKEL_TXT_APP_DEFINITIONS = lib.helper.load_jsons_as_text(
    'skel/easytravel/apprules')

APP_REQUESTATTRIBUTES = lib.helper.load_jsons(
    'skel/easytravel/requestattributes')

APP_AUTOTAGGING = lib.helper.load_jsons(
    'skel/easytravel/autotagging')

APP_DASHBOARDS = lib.helper.load_jsons(
    'skel/easytravel/dashboards')

APP_MANAGEMENTZONES = lib.helper.load_jsons(
    'skel/easytravel/managementzones')

SKEL_AWS_USERDATA = (open(AWS_USERDATA_FILE, 'r')).read()


class EmptyResponse:
    status_code = 500
    reason = 'Unkown'
    content = 'Empty'


def check_create_dir(dir_name):
    if not os.path.exists(dir_name):
        os.makedirs(dir_name)


# Logging configuration
# Create log directory at initialization
check_create_dir(LOG_DIR)
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', filename=LOG_DIR + '/' + LOG_FILE,
                    level=logging.INFO)

# Add logging also to the console of the running program
logging.getLogger().addHandler(logging.StreamHandler())


def getHeaderJson():
    return {'content-type': 'application/json'}


def getHeader():
    return {'content-type': 'application/json', "Authorization": "Api-Token " + CMC_TOKEN}


def getHeaderToken(token):
    return {'content-type': 'application/json', "Authorization": "Api-Token " + token}


def getHeaderAuthorization(token):
    return {'content-type': 'application/json', "Authorization": token}

# For handling Tenants with an invalid SSL Certificate just set it to false.


def verifyRequest():
    return True


def getAuthenticationHeader():
    return {"Authorization": "Api-Token " + CMC_TOKEN}


def do_cmc_get(endpoint):
    response = requests.get(
        CMC_URL + endpoint, headers=getHeader(), verify=verifyRequest())
    logging.debug('GET Reponse content: ' +
                  str(response.content) + '-' + endpoint)
    return response


def do_cmc_post(endpoint, data):
    response = requests.post(
        CMC_URL + endpoint, json=data, headers=getHeader(), verify=verifyRequest())
    logging.debug('POST Reponse content: ' +
                  str(response.content) + '-' + endpoint)
    return response


def do_tenant_put(endpoint, data, put_data):
    tenantUrl = data[key_tenantUrl]
    tenantToken = data[key_tenantToken]
    response = requests.put(tenantUrl + endpoint, json=put_data,
                            headers=getHeaderToken(tenantToken), verify=verifyRequest())
    logging.debug('PUT Reponse content: ' +
                  str(response.content) + '-' + endpoint)
    return response


def do_tenant_post_list(endpoint, data, post_data_list):
    responses = []
    for post_data in post_data_list:
        responses.append(do_tenant_post(endpoint, data, post_data))

    return responses


def do_tenant_post(endpoint, data, post_data):
    tenantUrl = data[key_tenantUrl]
    tenantToken = data[key_tenantToken]
    response = requests.post(tenantUrl + endpoint, json=post_data,
                             headers=getHeaderToken(tenantToken), verify=verifyRequest())
    logging.debug('POST Reponse content: ' +
                  str(response.content) + '-' + endpoint)
    return response


def do_tenant_get(endpoint, data):
    tenantUrl = data[key_tenantUrl]
    tenantToken = data[key_tenantToken]
    response = requests.get(
        tenantUrl + endpoint, headers=getHeaderToken(tenantToken), verify=verifyRequest())
    logging.debug('GET Reponse content: ' +
                  str(response.content) + '-' + endpoint)
    return response


def get_url(data):
    """
    Searchs for the publicDns or the publicIpAdress and returns it with an HTTP protocol
    """
    ipdns = get_ip_or_dns(data)
    protocol = 'http://'
    url = None
    if ipdns:
        url = protocol + ipdns
    return url


def get_ip_or_dns(data):
    """
    Searchs for the publicDns or the publicIpAddress
    """
    publicDns = data[key_publicDnsName]
    publicIpAddress = data[key_publicIpAddress]
    if publicDns:
        return publicDns
    elif publicIpAddress:
        return publicIpAddress
    return None


def do_http_get(endpoint, data):
    response = EmptyResponse()
    url = get_url(data)
    if not url:
        response.reason = 'No IP found'
        return response
    try:
        response = requests.get(
            url + endpoint, verify=verifyRequest(), timeout=5)
        logging.debug('GET Reponse content: ' +
                      str(response.content) + '-' + endpoint)
    except:
        e = sys.exc_info()[0]
        response.reason = str(e)
    return response


def do_cmc_delete(endpoint):
    response = requests.delete(
        CMC_URL + endpoint, headers=getHeader(), verify=verifyRequest())
    logging.debug('DELETE Reponse content: ' +
                  str(response.content) + '-' + endpoint)
    return response


def save_json(directory, filename, data):
    if directory:
        check_create_dir(directory)
        fullpath = directory + '/' + filename + '-' + getNowAsString() + '.json'
    else:
        # TODO : For later... save_json is necesary?
        fullpath = filename + '-' + getNowAsString() + '.json'
    with open(fullpath, 'w') as f:
        json.dump(data, f)


def replace_tenant_ids(json_data, data):
    tenantId = data[key_tenantId]
    json_data['tenantConfigDto']['tenantUUID'] = tenantId
    json_data['tenantConfigDto']['alias'] = tenantId
    json_data['tenantConfigDto']['internalAlias'] = tenantId
    json_data['tenantConfigDto']['displayName'] = data[key_firstName] + \
        ' ' + data[key_lastName]
    return


def replace_user_ids(json_data, data):
    # Select 'id' as userId if found on the CSV, otherwise the email
    userId = data.get(key_id)
    if userId:
        json_data[key_id] = userId
    else:
        json_data[key_id] = data[key_email]

    json_data[key_email] = data[key_email]
    json_data[key_firstName] = data[key_firstName]
    json_data[key_lastName] = data[key_lastName]
    json_data['groups'] = [data[key_groupId]]
    return


def replace_group_ids(json_data, data):
    groupId = data[key_groupId]
    tenantId = data[key_tenantId]

    isClusterAdminGroup = str_bool(data.get(key_isClusterAdminGroup))

    json_data['name'] = groupId
    json_data['accessRight']['VIEWER'] = [tenantId]
    json_data['accessRight']['MANAGE_SETTINGS'] = [tenantId]
    json_data['accessRight']['AGENT_INSTALL'] = [tenantId]
    json_data['accessRight']['LOG_VIEWER'] = [tenantId]
    json_data['accessRight']['VIEW_SENSITIVE_REQUEST_DATA'] = [tenantId]
    json_data['accessRight']['CONFIGURE_REQUEST_CAPTURE_DATA'] = [tenantId]
    if isClusterAdminGroup:
        json_data[key_isClusterAdminGroup] = isClusterAdminGroup
    return


def load_users_csv():
    '''
    Users will be loaded in the CSV_DATA Object and will be saved in data/users_to_create.json
    '''

    # Open the CSV
    f = open(CSV_DIR + '/' + CSV_FILE)
    # Change each fieldname to the appropriate field name. I know, so difficult.
    csvReader = csv.DictReader(f, delimiter=";")
    for row in csvReader:

        user_id = row.get(key_id)
        if not user_id:
            user_id = row[key_email]

        tenantId = row.get(key_tenantId)
        if not tenantId:
            firstName = row.get(key_firstName)
            lastName = row.get(key_lastName)

            # prepare fields for faster and better parsing
            tenantId = firstName + '-' + lastName
            # to small letters and replace emptyspace for dash
            # TODO: For later... Parse/Validate Names with unsupported characters
            tenantId = tenantId.lower().strip(' ').replace(' ', '-')
            row[key_tenantId] = tenantId

        if not bool(re.match(regex_valid_chars, tenantId)):
            logging.warning("TenantID is not valid for " + user_id +
                            " - " + tenantId + "\t row will be skipped")
            row['skip'] = 'true'
            # add data as it is
            CSV_DATA[user_id] = row
            continue

        # Functionality for parsing Perform URL adds protocol if tenantId contains .com and not a protocol
        if 'http' not in tenantId and '.com' in tenantId and not row.get(key_tenantUrl):
            row[key_tenantUrl] = 'https://' + tenantId

        elif not row.get(key_tenantUrl):
            row[key_tenantUrl] = CMC_URL + '/e/' + tenantId

        if not row.get(key_groupId):
            row[key_groupId] = tenantId + '-group'

        CSV_DATA[user_id] = row
    return


def validate_set_action_status(response, data, action, defaultvalue=''):

    result = defaultvalue
    action_status = True

    if 200 <= response.status_code <= 300:
        # If not default value, then set the reason
        if not defaultvalue:
            result = response.reason

        action_status = True
    else:
        result = str(response.status_code)
        logging.warning(action + ':\t' + data[key_email] + ': code:' + result +
                        ' reason:' + response.reason + ' Content:' + str(response.content))
        action_status = False

    data[action] = result
    logging.info(action + ':\t' + data[key_email] + ':' + result)
    logging.debug(action + ':\t' + data[key_email] +
                  ':' + result + 'Content:' + str(response.content))
    return action_status


def create_user(data):
    if not ACTION_CREATE_USER:
        return True
    post_data = copy.deepcopy(SKEL_USER)
    # Set user_id fields
    replace_user_ids(post_data, data)
    response = do_cmc_post(API_EP_CM_USERS, post_data)
    return validate_set_action_status(response, data, 'create_user')


def create_allinone_token(data):
    if not ACTION_CREATE_ALLINONETOKEN:
        return True
    post_data = SKEL_TOKEN
    response = do_cmc_post(API_EP_CM_CREATETOKEN_TENANT +
                           data[key_tenantId], post_data)

    if 200 <= response.status_code <= 300:
        data[key_tenantToken] = json.loads(response.text)['tokenId']

    return validate_set_action_status(response, data, 'create_token')


def create_user_group(data):
    if not ACTION_CREATE_USERGROUP:
        return True
    post_data = copy.deepcopy(SKEL_GROUP)
    replace_group_ids(post_data, data)
    response = do_cmc_post(API_EP_CM_GROUPS, post_data)
    return validate_set_action_status(response, data, 'create_user_group')


def delete_user(data):
    if not ACTION_DELETE_USER:
        return True
    userId = data[key_email]
    response = do_cmc_delete(API_EP_CM_USERS + userId)
    return validate_set_action_status(response, data, 'delete_user')


def delete_user_group(data):
    if not ACTION_DELETE_USERGROUP:
        return True
    groupId = data[key_groupId]
    response = do_cmc_delete(API_EP_CM_GROUPS + groupId)
    return validate_set_action_status(response, data, 'delete_user_group')


def environment_create_dashboards(data):

    # Set up the Dashboard
    post_data = copy.copy(SKEL_TXT_DASHBOARD)
    # Replace in Textfile
    post_data = post_data.replace(key_firstName, str(data.get(key_firstName)))
    post_data = post_data.replace(key_lastName, str(data.get(key_lastName)))
    post_data = post_data.replace(
        key_publicDnsName, str(data.get(key_publicDnsName)))
    post_data = post_data.replace(
        key_publicIpAddress, str(data.get(key_publicIpAddress)))

    post_data = post_data.replace(
        '/p/', str('/p/-' + data.get('session')))
    # Convert to JSON
    post_data = json.loads(post_data)

    # At last the Home Dashboard
    response = do_tenant_post(API_EP_TENANT_DASHBOARDS, data, post_data)
    
    # First all other Dashboards
    responses = do_tenant_post_list(
        API_EP_TENANT_DASHBOARDS, data, APP_DASHBOARDS)
    logging.info('Dashboards rules:\t' +
                 data[key_email] + ':' + str(responses))

    validate_set_action_status(response, data, 'create_dashboards')

    return


def set_up_environment(data):
    if not ACTION_SET_UP_ENV:
        return True

    """
    # Create Dashboard
    """
    environment_create_dashboards(data)

    # Change name My WebApplication to CathAll for NonConfiguredApps
    response = do_tenant_put(API_EP_TENANT_DEFAULTAPP, data, SKEL_DEFAULTAPP)
    validate_set_action_status(response, data, 'rename_defaultapp')

    app1_key = 'application-1'
    app2_key = 'application-2'

    # Create EasyTravel Angular
    response = do_tenant_post(API_EP_TENANT_APP, data, SKEL_APPLICATION1)
    validate_set_action_status(
        response, data, app1_key, json.loads(response.text)['id'])

    # Create EasyTravel Classic
    response = do_tenant_post(API_EP_TENANT_APP, data, SKEL_APPLICATION2)
    validate_set_action_status(
        response, data, app2_key, json.loads(response.text)['id'])

    # Add App DetectionRules
    values_to_replace = {app1_key: str(
        data.get(app1_key)), app2_key: str(data.get(app2_key))}
    APP_DEFINITIONS = copy_array_and_replace_key_values_in_dict(
        SKEL_TXT_APP_DEFINITIONS, values_to_replace)

    responses = do_tenant_post_list(
        API_EP_TENANT_APPDETECTION_RULES, data, APP_DEFINITIONS)
    logging.info('AppDetectionRules:\t' +
                 data[key_email] + ':' + str(responses))

    # Add RequestAttributes
    responses = do_tenant_post_list(
        API_EP_TENANT_REQUESTATTRIBUTES, data, APP_REQUESTATTRIBUTES)
    logging.info('RequestAttributes:\t' +
                 data[key_email] + ':' + str(responses))

    # Add Auto Tagging Rules
    responses = do_tenant_post_list(
        API_EP_TENANT_AUTOTAGGING, data, APP_AUTOTAGGING)
    logging.info('Autotagging rules:\t' +
                 data[key_email] + ':' + str(responses))

    # Add Management Zones
    responses = do_tenant_post_list(
        API_EP_TENANT_MANAGEMENTZONES, data, APP_MANAGEMENTZONES)
    logging.info('Management zones:\t' +
                 data[key_email] + ':' + str(responses))

    # Add Synthetic test
    """ 
    post_data = copy.copy(SKEL_TXT_MONITOR)
    post_data = post_data.replace(
        key_publicDnsName, str(data.get(key_publicDnsName)))
    post_data = json.loads(post_data)
    response = do_tenant_post(API_EP_TENANT_MONITOR, data, post_data)
    validate_set_action_status(response, data, 'create_monitor')
    """

    return True


def copy_array_and_replace_key_values_in_dict(json_array, replacement_dictionary):
    """ Function to copy an array of JSON files loaded as text, do a replacement from a dictionary (replacing the keys for the values)
    and loading it back as an JSON Object
    """
    NEW_JSON_ARRAY = []
    for jsonAsString in json_array:
        j = copy.copy(jsonAsString)
        for k, v in replacement_dictionary.items():
            j = j.replace(k, v)
        NEW_JSON_ARRAY.append(json.loads(j))

    return NEW_JSON_ARRAY


def create_tenant(data):
    if not ACTION_CREATE_TENANT:
        return True

    post_data = copy.deepcopy(SKEL_TENANT)
    # Set tenant_id fields
    replace_tenant_ids(post_data, data)
    response = do_cmc_post(API_EP_CM_CREATE_TENANT, post_data)
    return validate_set_action_status(response, data, 'create_tenant')


def remove_tenant(data):
    if not ACTION_REMOVE_TENANT:
        return True
    tenantId = data[key_tenantId]
    response = do_cmc_delete(API_EP_CM_REMOVE_TENANT + tenantId)
    return validate_set_action_status(response, data, 'remove_tenant')


def deactivate_tenant(data):
    if not ACTION_DEACTIVATE_TENANT:
        return True
    tenantId = data[key_tenantId]
    response = do_cmc_post(API_EP_CM_DEACTIVATE_TENANT + tenantId, "")
    return validate_set_action_status(response, data, 'deactivate_tenant')


def do_save_cmc_data():
    r = do_cmc_get(API_EP_CM_TENANTCONFIGS)
    TENANTS = json.loads(r.text)
    save_json(DATA_DIR, "tenantconfig", TENANTS)

    r = do_cmc_get(API_EP_CM_GROUPS)
    USER_GROUPS = json.loads(r.text)
    save_json(DATA_DIR, "groups", USER_GROUPS)

    r = do_cmc_get(API_EP_CM_USERS)
    USERS = json.loads(r.text)
    save_json(DATA_DIR, "users", USERS)
    return


def get_ec2_user_data(tenantUrl, tenantToken):
    user_data = copy.copy(SKEL_AWS_USERDATA)
    # Set Tenant
    user_data = user_data.replace('TENANT=', 'TENANT=' + tenantUrl, 1)
    # Set API-Token
    user_data = user_data.replace('PAASTOKEN=', 'PAASTOKEN=' + tenantToken, 1)
    return user_data


def test_ssh_connection(data):
    if not ACTION_TEST_SSH_CONNECTION:
        return True

    """
    TODO Extract SSH Commands and pass it to a file comma separated like: docker pull, False
    nohup sh setup/setup_environment.sh >test.log 2>&1 &
    """
    cmds = []
    cmds.append(['docker pull shinojosa/bankjob:perform2020', False])
    cmds.append(['docker stop bankjob', False])
    cmds.append(['docker rm bankjob', False])
    cmds.append(
        ['docker run -d --name bankjob shinojosa/bankjob:perform2020', False])
    execute_ssh_command(data, cmds, True)

    return


class SshClient:
    "A wrapper of paramiko.SSHClient for executing with sudo rights"
    TIMEOUT = 4

    def __init__(self, host, port, username, password, key=None, passphrase=None):
        self.username = username
        self.password = password
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if key is not None:
            key = paramiko.RSAKey.from_private_key(
                StringIO(key), password=passphrase)
        self.client.connect(host, port, username=username,
                            password=password, pkey=key, timeout=self.TIMEOUT)

    def close(self):
        if self.client is not None:
            self.client.close()
            self.client = None

    def execute(self, command, sudo=False):
        feed_password = False
        if sudo and self.username != "root":
            command = 'sudo -S -p \'\' %s' % command
            feed_password = self.password is not None and len(
                self.password) > 0
        stdin, stdout, stderr = self.client.exec_command(command)
        if feed_password:
            stdin.write(self.password + "\n")
            stdin.flush()
        return {'out': stdout.readlines(),
                'err': stderr.readlines(),
                'retval': stdout.channel.recv_exit_status()}


def execute_ssh_command(data, cmds, as_sudo=False):
    """
    Execute a ssh command
    """
    response = EmptyResponse()
    ssh = None
    action = 'ssh_cmd'
    ipdns = get_ip_or_dns(data)

    retvals = []
    try:
        if ipdns is None:
            raise Exception('no dns nor ip found')

        sshUser = data['sshUser']
        sshPassword = data['sshPassword']
        ssh = SshClient(ipdns, port=22, username=sshUser, password=sshPassword)

        retval = 0
        for cmd in cmds:
            c = cmd[0]
            asSudo = cmd[1]
            logging.info(data[key_email] + ' IP:'+ipdns+' exec:' + str(cmd))
            ret = ssh.execute(c, asSudo)

            retval = retval + ret['retval']
            retvals.append(ret['retval'])
            logging.info(data[key_email] + ' IP:'+ipdns + ' out :' + str(ret['out'])+' err ' +
                         str(ret['err'])+'[' + str(ret['retval']) + ']')

        response.status_code = 200
        response.reason = str(retvals)

    except Exception as e:
        if ssh is not None:
            ssh.close()
        logging.warning('Error on SSH for ' +
                        data[key_email] + ' ' + str(e.args[0]))
        response.status_code = 500
        response.reason = str(e.args[0])

    finally:
        if ssh is not None:
            ssh.close()

    return validate_set_action_status(response, data, action, str(retvals))


def test_tenant_api(data):
    if not ACTION_TEST_TENANT_API:
        return True
    action = 'tenant_api'
    response = do_tenant_get(API_EP_TENANT_DASHBOARDS, data)
    return validate_set_action_status(response, data, action)


def test_easytravel_rest_ping(data):
    if not ACTION_TEST_ET_PING:
        return True
    action = 'easytravel_ping'
    response = do_http_get(API_EASYTRAVEL_PING, data)
    return validate_set_action_status(response, data, action)


def easytravel_plugin(data, plugin, enable):
    action = plugin
    response = do_http_get(API_EASYTRAVEL_PLUGIN +
                           plugin + '&enabled=' + enable, data)
    return validate_set_action_status(response, data, action, enable)


def fetch_dns_ec2_instance(data):
    if not ACTION_FETCH_EC2INSTANCE:
        return True

    action = 'ec2_dns_name'
    # Load client
    ec2 = boto3.resource('ec2')

    # Load ec2 instance
    instanceId = data['instanceId']
    instance = ec2.Instance(instanceId)

    # Just check if the public DNS/IP is there.
    if instance.public_dns_name:
        data[key_publicDnsName] = instance.public_dns_name
        data[key_publicIpAddress] = instance.public_ip_address
        logging.info(action + ':\t' + data[key_email] + ': InstanceId: ' +
                     instanceId + ' :' + instance.public_dns_name)
        return True
    elif instance.state['Name'] == 'running':
        logging.warning(action + ':\t' + data[key_email] + ': InstanceId: ' + instanceId +
                        ' : public IP not assigned and the machine is already running. Check your ec2 config')
        return False

    elif instance.state['Name'] == 'pending':
        logging.info(action + ':\t' + data[key_email] +
                     ': waiting until the instance is running to get the public ip ' + instanceId)

        """ Since we are impatient and we know that the dns and IP are long bofore the
        running state assigned, we try to fetch them before the running state.
        """
        while instance.state['Name'] == 'pending':
            instance.reload()
            if instance.public_dns_name:
                data[key_publicDnsName] = instance.public_dns_name
                data[key_publicIpAddress] = instance.public_ip_address
                logging.info(
                    action + ':\t' + data[key_email] + ': InstanceId: ' + instanceId + ' : ' + instance.public_dns_name)
                return True
            else:
                logging.info(
                    action + ':\t' + data[key_email] + ': sleeping two seconds to fetch again: ' + instanceId)
                time.sleep(2)

        # This check if it enters running state and we did not check before
        if instance.public_dns_name:
            data[key_publicDnsName] = instance.public_dns_name
            data[key_publicIpAddress] = instance.public_ip_address
            logging.info(action + ':\t' + data[key_email] + ': Running InstanceId:' +
                         instanceId + ' : ' + instance.public_dns_name)
            return True
        else:
            logging.warning(action + ':\t' + data[key_email] + ': InstanceId:' + instanceId +
                            ': public IP not assigned and the machine is already running. Check your ec2 config')
            return False
    else:
        logging.warning(action + ':\t' + data[key_email] + ': InstanceId:' + instanceId +
                        ': the instance is not in a correct state. Stopped or terminated?')
        return False

    return False


def delete_ec2_instance(data):
    if not ACTION_DELETE_EC2INSTANCE:
        return True
    instanceId = data['instanceId']
    ec2_client = boto3.client('ec2')
    action = 'delete_ec2_instance'
    # TODO:  For later... Add delete-ec2-status when failed
    try:
        r = ec2_client.terminate_instances(InstanceIds=[instanceId])
        result = 'OK'
        data[action] = result
        logging.info(action + ':\t' + data[key_email] + ':' + result)
    except ClientError as e:
        logging.warning("problem deleting ec2-instance:" + str(e))
        return False
    return True


def create_ec2_instance(data):
    """ Provision and launch an EC2 instance
    The instances will be created in the region as the config defined in your AWS file.
    The method returns without waiting for the instance to reach
    a running state.
    :param image_id: ID of AMI to launch, such as 'ami-XXXX'
    :param instance_type: string, such as 't2.micro'
    :param keypair_name: string, name of the key pair
    :return Dictionary containing information about the instance. If error,
    returns None.
    """
    if not ACTION_CREATE_EC2INSTANCE:
        return True

    # TODO: For later... Parametrize Image provitioning
    """Oregon us-west-2
    ubuntu_image = "ami-06d51e91cea0dac8d"
    keypair_name = "perform"
    security_groups = ["perform"]
    securityGroupId = 'perform'
    """

    """London eu-west-2
    # old
    # ubuntu_image = "ami-0cbe2951c7cd54704"
    ubuntu_image = "ami-0fab23d0250b9a47e"
    keypair_name = "bc19-lon.pem"
    security_groups = ["launch-wizard-3"]
    securityGroupId = 'launch-wizard-3'
    """

    """Irland eu-west-1
    # old
    # ubuntu_image = "ami-03746875d916becc0"
    ubuntu_image = "ami-03ef731cc103c9f09"
    keypair_name = "bootcamp-19"
    security_groups = ["BootcampOpen"]
    securityGroupId = 'BootcampOpen'
    """

    # Oregon
    # 2 security groups perform, opentoworld
    ubuntu_image = "ami-06d51e91cea0dac8d"
    keypair_name = "perform"
    security_groups = ["opentoworld"]
    securityGroupId = 'opentoworld'

    instance_type = "t2.large"
    "NoteToSelf: Security Group by Name and not by ID."

    ec2Name = data[key_tenantId]
    owner = data[key_email]
    tenantToken = str(data.get(key_tenantToken))
    # Functionality for overriding the allInOneToken for SaaS installers
    paasToken = str(data.get('paasToken'))
    if paasToken not in (None, ''):
        paasToken = tenantToken
    tenantUrl = str(data.get(key_tenantUrl))
    ec2_user_data = get_ec2_user_data(tenantUrl, paasToken)

    tags = [{'Key': 'Name', 'Value': ec2Name},
            {'Key': 'Perform', 'Value': '2020'},
            {'Key': key_tenantUrl, 'Value': tenantUrl},
            {'Key': key_tenantToken, 'Value': tenantToken},
            {'Key': 'paasToken', 'Value': paasToken},
            {'Key': 'Customer', 'Value': owner},
            {'Key': 'Owner', 'Value': owner}]
    tag_specification = [{'ResourceType': 'instance', 'Tags': tags}]

    block_device_mappings = [{'DeviceName': '/dev/sda1',
                              'Ebs': {'VolumeSize': 30, 'DeleteOnTermination': True}}]

    # Provision and launch the EC2 instance
    ec2_client = boto3.client('ec2')
    action = 'create_ec2_instance'
    instanceId = ''
    content = ''
    try:
        r = ec2_client.run_instances(ImageId=ubuntu_image,
                                     InstanceType=instance_type,
                                     KeyName=keypair_name,
                                     MinCount=1,
                                     MaxCount=1,
                                     SecurityGroups=security_groups,
                                     TagSpecifications=tag_specification,
                                     BlockDeviceMappings=block_device_mappings,
                                     UserData=ec2_user_data, SecurityGroupIds=[securityGroupId])

        instanceId = r['Instances'][0]['InstanceId']
        content = r['Instances'][0]
        data['instanceId'] = instanceId
        result = 'OK'
        data[action] = result
        logging.info(action + ':\t' + data[key_email] + ':' + result)
        logging.debug(
            action + ':\t' + data[key_email] + ':' + result + ':Response: ' + str(content))

    except ClientError as e:
        logging.error(action + ':\t' + data[key_email] + str(e) + str(content))
        return False
    return True


def str_bool(s):
    if s and s.lower().strip(' ') == 'true':
        return True
    else:
        return False


def skip_in_data(data):
    skip = str_bool(data.get(key_skip))
    if skip:
        logging.info('Skipping row for:\t' + data[key_email])
    return skip


def action_test():
    """
    Action to test connections, tenants, tokens, ids.
    """
    for id in CSV_DATA:
        data = CSV_DATA[id]

        # If skip is declared, we go to the next row
        if skip_in_data(data):
            continue

        test_ssh_connection(data)

        test_tenant_api(data)

        test_easytravel_rest_ping(data)

    save_json(DATA_DIR, "action-test-results", CSV_DATA)
    return


def action_easytravel():
    """
    EasyTravel functions, Ping, Plugin
    """
    save_results = True
    global ACTION_TEST_ET_PING

    for id in CSV_DATA:
        data = CSV_DATA[id]

        # If skip is declared, we go to the next row
        if skip_in_data(data):
            continue

        if len(sys.argv) >= 3:
            command = sys.argv[2]

            if command == 'ping':
                ACTION_TEST_ET_PING = True
                test_easytravel_rest_ping(data)
            elif command == 'plugin':
                if len(sys.argv) >= 5:
                    plugin = sys.argv[3]
                    enable = sys.argv[4]
                    easytravel_plugin(data, plugin, enable)
                else:
                    logging.warning(
                        "EasyTravel actions are [ping] and [plugin 'pluginname' enable='true/false']")
                    save_results = False
                    break
            else:
                logging.info("action not recognized")
                save_results = False

        else:
            logging.info(
                "EasyTravel actions are [ping] and [plugin 'pluginname' enable='true/false']")
            save_results = False
            break
    return save_results


def action_create():
    """
    Function where the different create actions will be executed.
    Users can be skipped if the skip=true flag is defined.
    if an action for a user fails, the loop will continue with the next row.
    """
    for id in CSV_DATA:
        data = CSV_DATA[id]

        # If skip is declared, we go to the next row
        if skip_in_data(data):
            continue

        if not create_tenant(data):
            continue

        if not create_user_group(data):
            continue

        if not create_user(data):
            continue

        if not create_allinone_token(data):
            continue

        if not create_ec2_instance(data):
            continue

        if not fetch_dns_ec2_instance(data):
            continue

        if not set_up_environment(data):
            continue

    save_json(DATA_DIR, "action-create-results", CSV_DATA)
    return



def disable_frequent_issue_detection():
    for id in CSV_DATA:
        data = CSV_DATA[id]
        # If skip is declared, we go to the next row
        if skip_in_data(data):
            continue

        tenantUrl = data[key_tenantUrl]
        tenantToken = data[key_tenantToken]
        put_data = json.loads(
            (open('skel/easytravel/frequentissue/frequentissueoff.json', 'r', encoding='utf8')).read())

        response = do_tenant_put(API_EP_TENANT_FREQUENTISSUE, data, put_data)
        validate_set_action_status(
            response, data, 'frequentissues', 'disabled')

    return


def action_config():
    """
    Variable dirty function for configuration
    """
    disable_frequent_issue_detection()
    return

    return


def action_remove():
    """
    Function where the different delete/remove actions will be executed. 
    Users can be skipped if the skip=true flag is defined.
    if an action for a user fails in here doesnt matter there is no dependency. We want to remove all we can for a user.
    """
    for id in CSV_DATA:
        data = CSV_DATA[id]
        # If skip is declared, we go to the next row
        if skip_in_data(data):
            continue

        deactivate_tenant(data)
        remove_tenant(data)
        delete_user_group(data)
        delete_user(data)
        delete_ec2_instance(data)

    save_json(DATA_DIR, "delete-results", CSV_DATA)
    return


def save_results(file):
    # At least email is declared.
    header = [key_email]
    data = CSV_DATA

    result_file = file

    ''' We Iterate two times for getting all the headers, 
    some objects might not have all attributes
    '''
    for id in data:
        keys = data[id].keys()
        # Add key to a header so so we get all headers of all rows
        for k in keys:
            if k not in header:
                header.append(k)

    csv_result = csv.DictWriter(
        open(result_file, "w", newline=''), delimiter=';', fieldnames=header)
    csv_result.writeheader()
    # Now write the values
    for id in data:
        csv_result.writerow(data[id])

    logging.info('Result file ' + result_file + ' written.')
    return


def do_dev():
    """
    Dev function for testing purpouses.
    """

    action_config()
    return
    data = CSV_DATA['sergio.hinojosa@dynatrace.com']

    cmds = []
    cmds.append(['whoami', False])
    cmds.append(['whoami', True])
    cmds.append(['ls', False])
    cmds.append(['pwd', False])
    cmds.append(['docker ps -a', False])

    execute_ssh_command(data, cmds)

    lib.helper.load_jsons_as_text('skel/easytravel/apprules')

    return


def do_validate():
    """
    Validate function. print out the config, count the users and print the actions.
    """
    try:
        # Print config
        logging.info(
            "\n====== [RTA] Rest Tenant Automation Configuration ======")
        for k, v in config.items():
            if isinstance(v, dict):
                logging.info("%s:" % (k))
                for subk, subv in v.items():
                    logging.info(" |-%-20s: %-10s" % (subk, subv))

                logging.info("\n")
            else:
                logging.info("%-10s: %s" % (k, v))

        logging.info("\nConfiguration loaded correctly.")
        load_users_csv()

        logging.info(
            "\nCSV file loaded correctly. Printing users with their control flags...")
        # Print flags
        logging.info("\n====== [RTA] Rest Tenant Automation Users ======")

        # Print Headers
        print_layout = "[%-2d] %-40s %-20s %-8s %-8s"
        logging.info(print_layout %
                     (0, "USER-ID", "TENANT-ID", "SKIP", "IS_ADMIN"))
        i = 0
        for id in CSV_DATA:
            data = CSV_DATA[id]
            is_skip = str_bool(data.get(key_skip))
            is_admin = str_bool(data.get(key_isClusterAdminGroup))

            # If skip is declared, we go to the next row
            i = i + 1
            logging.info(print_layout %
                         (i, id, data.get(key_tenantId), is_skip, is_admin))

    except Exception as e:  # catch all exceptions
        exc_type, exc_value, exc_traceback = sys.exc_info()
        logging.error(
            "There is an error validating, please fix it before executing.")
        logging.error(traceback.print_exc())
        traceback.print_exc()

    return


def getNowAsString():
    ts = time.time()
    return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H-%M-%S')


def main():
    try:
        printUsage = False
        saveResults = False

        logging.info("----------------------------------------------")
        logging.info("Starting Dynatrace RTA Rest Tenant Automation\n")

        if len(sys.argv) >= 2:
            command = sys.argv[1]

            if command == 'create':
                logging.info("====== Create action called ======")
                load_users_csv()
                action_create()
                saveResults = True

            elif command == 'test':
                logging.info("====== Test action called ======")
                load_users_csv()
                action_test()
                saveResults = True

            elif command == 'remove':
                logging.info("====== Remove action called ======")
                load_users_csv()
                action_remove()
                saveResults = True

            elif command == 'easytravel':
                logging.info("====== EasyTravel action called ======")
                load_users_csv()
                saveResults = action_easytravel()

            elif command == 'dev':
                load_users_csv()
                logging.info("====== Dev Test function called ======")
                do_dev()

            elif command == 'config':
                load_users_csv()
                logging.info("====== Config  function called ======")
                action_config()
                saveResults = True

            elif command == 'help':
                printUsage = True

            elif command == 'validate':
                logging.info(
                    "====== Validating configuration and users ======")
                do_validate()
                printUsage = True

            else:
                logging.warning("Command not recognized:" + command)
                printUsage = True

            if saveResults:
                # If an action is performed we save the data
                save_json(DATA_DIR, "results", CSV_DATA)
                # Write Backup
                save_results(CSV_TEMP_DIR + '/' +
                             getNowAsString() + '-' + CSV_FILE)
                # Overwrite Original
                save_results(CSV_DIR + '/' + CSV_FILE)
        else:
            logging.warning("You need to give at least one argument")
            printUsage = True

    except Exception as e:  # catch all exceptions
        exc_type, exc_value, exc_traceback = sys.exc_info()
        logging.error(traceback.print_exc())
        traceback.print_exc()
        # Save it in object
        save_json(DATA_DIR, "error-results", CSV_DATA)
        # Write Backup
        save_results(CSV_TEMP_DIR + '/error-' +
                     getNowAsString() + '-' + CSV_FILE)

    if printUsage:
        doUsage(sys.argv)
    else:
        print("\nDone automating... have a nice day")
    exit


def get_usage_as_string():
    return """
Dynatrace REST Tenant Automation 
=======================================================
Usage: rta.py <command>
commands: help       = Prints this options
commands: validate   = Validates and prints the config file, reads the CSV file and prints the users and control flags
commands: create     = Creates the tenants, resources and sets-up the environment
commands: remove     = Removes the tenants and deletes the resources
commands: test       = Calls test functions like testing an API with a token or an SSH connection
commands: easytravel = Calls EasyTravel functionality
** For more information read the README.md file **
=======================================================
"""


def doUsage(args):
    "Just printing Usage"
    usage = get_usage_as_string()
    print(usage)
    exit


# Start Main
if __name__ == "__main__":
    main()
