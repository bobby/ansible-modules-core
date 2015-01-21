#!/usr/bin/python
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

DOCUMENTATION = '''
---
module: route53
version_added: "1.3"
short_description: add or delete zones and records in Amazons Route53 DNS service
description:
     - Creates and deletes DNS zones and records in Amazons Route53 service
options:
  state:
    description:
      - Specifies the action to take.
    required: true
    default: null
    aliases: []
    choices: [ 'list', 'present', 'absent' ]
  zone:
    description:
      - The DNS zone to create, modify, or delete
    required: true
    default: null
    aliases: []
  vpc_id:
    description:
      - The VPC to associate with this hosted zone.  If this option is provided, the hosted zone will be private.
    required: false
    default: null
    aliases: []
  region:
    description:
      - The AWS region for the VPC to associate with this hosted zone.  Must be specified if vpc_id is provided.
    required: false
    default: null
    aliases: [aws_region, ec2_region]
  record:
    description:
      - The full DNS record to create or delete.
    required: false
    default: null
    aliases: []
  ttl:
    description:
      - The TTL to give the new record.
    required: false
    default: 3600 (one hour)
    aliases: []
  type:
    description:
      - The type of DNS record to create.  Must be specified if record is provided.
    required: false
    default: null
    aliases: []
    choices: [ 'A', 'CNAME', 'MX', 'AAAA', 'TXT', 'PTR', 'SRV', 'SPF', 'NS' ]
  value:
    description:
      - The new value when creating a DNS record.  Multiple comma-spaced values are allowed.  When deleting a record all values for the record must be specified or Route53 will not delete it.
    required: false
    default: null
    aliases: []
  aws_secret_key:
    description:
      - AWS secret key.
    required: false
    default: null
    aliases: ['ec2_secret_key', 'secret_key']
  aws_access_key:
    description:
      - AWS access key.
    required: false
    default: null
    aliases: ['ec2_access_key', 'access_key']
  overwrite:
    description:
      - Whether an existing record should be overwritten on create if values do not match
    required: false
    default: null
    aliases: []
  retry_interval:
    description:
      - In the case that route53 is still servicing a prior request, this module will wait and try again after this many seconds. If you have many domain names, the default of 500 seconds may be too long.
    required: false
    default: 500
    aliases: []
requirements: [ "boto" ]
author: Bruce Pennypacker
'''

EXAMPLES = '''
# Add new.foo.com zone (public hosted zone)
- route53:
      state: present
      zone: foo.com

# Add new.foo.com zone in a VPC (private hosted zone)
- route53:
      state: present
      zone: foo.com
      vpc_id: vpc-1234abcd
      region: us-east-1

# Delete new.foo.com zone (public hosted zone)
- route53:
      state: absent
      zone: foo.com

# Add new.foo.com as an A record with 3 IPs
- route53:
      state: present
      zone: foo.com
      record: new.foo.com
      type: A
      ttl: 7200
      value: 1.1.1.1,2.2.2.2,3.3.3.3

# Retrieve the details for new.foo.com
- route53:
      state: list
      zone: foo.com
      record: new.foo.com
      type: A
  register: rec

# Delete new.foo.com A record using the results from the list state
- route53:
      state: absent
      zone: foo.com
      record: "{{ rec.set.record }}"
      type: "{{ rec.set.type }}"
      value: "{{ rec.set.value }}"

# Add an AAAA record.  Note that because there are colons in the value
# that the entire parameter list must be quoted:
- route53:
      state: "present"
      zone: "foo.com"
      record: "localhost.foo.com"
      type: "AAAA"
      ttl: "7200"
      value: "::1"

# Add a TXT record. Note that TXT and SPF records must be surrounded
# by quotes when sent to Route 53:
- route53:
      state: "present"
      zone: "foo.com"
      record: "localhost.foo.com"
      type: "TXT"
      ttl: "7200"
      value: '"bar"'
'''

import sys
import time

try:
    import boto
    from boto import route53
    from boto.route53.record import ResourceRecordSets
except ImportError:
    print "failed=True msg='boto required for this module'"
    sys.exit(1)

def commit(changes, retry_interval):
    """Commit changes, but retry PriorRequestNotComplete errors."""
    retry = 10
    while True:
        try:
            retry -= 1
            return changes.commit()
        except boto.route53.exception.DNSServerError, e:
            code = e.body.split("<Code>")[1]
            code = code.split("</Code>")[0]
            if code != 'PriorRequestNotComplete' or retry < 0:
                raise e
            time.sleep(float(retry_interval))

def main():
    argument_spec = ec2_argument_spec()
    argument_spec.update(dict(
            state           = dict(choices=['list', 'present', 'absent'], required=True),
            zone            = dict(required=True),
            vpc_id          = dict(required=False),
            record          = dict(required=False),
            ttl             = dict(required=False, default=3600),
            type            = dict(choices=['A', 'CNAME', 'MX', 'AAAA', 'TXT', 'PTR', 'SRV', 'SPF', 'NS'], required=False),
            value           = dict(required=False),
            overwrite       = dict(required=False, type='bool'),
            retry_interval  = dict(required=False, default=500)
        )
    )
    module = AnsibleModule(argument_spec=argument_spec)

    state_in          = module.params.get('state')
    zone_in           = module.params.get('zone')
    ttl_in            = module.params.get('ttl')
    record_in         = module.params.get('record')
    type_in           = module.params.get('type')
    value_in          = module.params.get('value')
    retry_interval_in = module.params.get('retry_interval')
    vpc_in            = module.params.get('vpc_id')

    ec2_url, aws_access_key, aws_secret_key, region = get_ec2_creds(module)

    if zone_in[-1:] != '.':
        zone_in += "."

    # connect to the route53 endpoint
    try:
        conn = boto.route53.connection.Route53Connection(aws_access_key, aws_secret_key)
    except boto.exception.BotoServerError, e:
        module.fail_json(msg = e.error_message)

    # Get all the existing hosted zones and save their ID's
    zones = {}
    results = conn.get_all_hosted_zones()
    for r53zone in results['ListHostedZonesResponse']['HostedZones']:
        zone_id = r53zone['Id'].replace('/hostedzone/', '')
        zones[r53zone['Name']] = zone_id

    if record_in:               # Perform operation on a specific Recordset
        if not zone_in in zones:
            errmsg = "Zone %s does not exist in Route53" % zone_in
            module.fail_json(msg = errmsg)

        value_list = ()

        if type(value_in) is str:
            if value_in:
                value_list = sorted(value_in.split(','))
        elif type(value_in)  is list:
            value_list = sorted(value_in)

        if record_in[-1:] != '.':
            record_in += "."
        if not type_in:
            module.fail_json(msg = "parameter 'type' required when 'record' is provided")
        if (state_in == 'present' or state_in == 'absent') and not value_in:
            module.fail_json(msg = "parameter 'value' required for present/absent when 'record' is provided")

        record = {}

        found_record = False
        sets = conn.get_all_rrsets(zones[zone_in])
        for rset in sets:
            # Due to a bug in either AWS or Boto, "special" characters are returned as octals, preventing round
            # tripping of things like * and @.
            decoded_name = rset.name.replace(r'\052', '*')
            decoded_name = decoded_name.replace(r'\100', '@')

            if rset.type == type_in and decoded_name == record_in:
                found_record = True
                record['zone'] = zone_in
                record['type'] = rset.type
                record['record'] = decoded_name
                record['ttl'] = rset.ttl
                record['value'] = ','.join(sorted(rset.resource_records))
                record['values'] = sorted(rset.resource_records)
                if value_list == sorted(rset.resource_records) and int(record['ttl']) == ttl_in and state_in == 'present':
                    module.exit_json(changed=False)

        if state_in == 'list':
            module.exit_json(changed=False, set=record)

        if state_in == 'absent' and not found_record:
            module.exit_json(changed=False)

        changes = ResourceRecordSets(conn, zones[zone_in])

        if state_in == 'present' and found_record:
            if not module.params['overwrite']:
                module.fail_json(msg = "Record already exists with different value. Set 'overwrite' to replace it")
            else:
                change = changes.add_change("DELETE", record_in, type_in, record['ttl'])
            for v in record['values']:
                change.add_value(v)

        if state_in == 'present' or state_in == 'absent':
            command = 'CREATE' if state_in == 'present' else 'DELETE'
            change = changes.add_change(command, record_in, type_in, ttl_in)
            for v in value_list:
                change.add_value(v)

        try:
            result = commit(changes, retry_interval_in)
        except boto.route53.exception.DNSServerError, e:
            txt = e.body.split("<Message>")[1]
            txt = txt.split("</Message>")[0]
            module.fail_json(msg = txt)

        module.exit_json(changed=True)
    else:                       # Perform operation on Hosted Zone
        if state_in == 'present':
            if zone_in in zones:
                module.exit_json(changed=False)
            else:
                if vpc_in:
                    if region:
                        vpc_created = conn.create_zone(zone_in, True, vpc_in, region)
                    else:
                        module.fail_json(msg = "parameter 'region' required when 'vpc_in' is provided")
                else:
                    vpc_created = conn.create_zone(zone_in)
                module.exit_json(changed=True, id=vpc_created.id)
        elif state_in == 'absent':
            if zone_in in zones:
                zone_id = zones[zone_in]
                # TODO: do we have to delete all records first?
                conn.delete_hosted_zone(zone_id)
                module.exit_json(changed=True)
            else:
                module.exit_json(changed=False)
        else:
            errmsg = "Zone %s does not exist in Route53" % zone_in
            module.fail_json(msg=errmsg)

# import module snippets
from ansible.module_utils.basic import *
from ansible.module_utils.ec2 import *

main()
