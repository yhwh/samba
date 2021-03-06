# Tests for Tests for source4/dsdb/samdb/ldb_modules/password_hash.c
#
# Copyright (C) Catalyst IT Ltd. 2017
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

"""
Base class for tests for source4/dsdb/samdb/ldb_modules/password_hash.c
"""

from samba.credentials import Credentials
from samba.samdb import SamDB
from samba.auth import system_session
from samba.tests import TestCase
from samba.ndr import ndr_unpack
from samba.dcerpc import drsblobs
from samba.dcerpc.samr import DOMAIN_PASSWORD_STORE_CLEARTEXT
from samba.dsdb import UF_ENCRYPTED_TEXT_PASSWORD_ALLOWED
from samba.tests import delete_force
import ldb
import os
import samba
import binascii
import md5


USER_NAME = "PasswordHashTestUser"
USER_PASS = samba.generate_random_password(32,32)
UPN       = "PWHash@User.Principle"

# Get named package from the passed supplemental credentials
#
# returns the package and it's position within the supplemental credentials
def get_package(sc, name):
    if sc is None:
        return None

    idx = 0
    for p in sc.sub.packages:
        idx += 1
        if name == p.name:
            return (idx, p)

    return None

# Calculate the MD5 password digest from the supplied user, realm and password
#
def calc_digest(user, realm, password):

    data = "%s:%s:%s" % (user, realm, password)
    return binascii.hexlify(md5.new(data).digest())


class PassWordHashTests(TestCase):

    def setUp(self):
        super(PassWordHashTests, self).setUp()

    # Add a user to ldb, this will exercise the password_hash code
    # and calculate the appropriate supplemental credentials
    def add_user(self, options=None, clear_text=False):
        self.lp = samba.tests.env_loadparm()
        # set any needed options
        if options is not None:
            for (option,value) in options:
                self.lp.set(option, value)

        self.creds = Credentials()
        self.session = system_session()
        self.ldb = SamDB(
            session_info=self.session,
            credentials=self.creds,
            lp=self.lp)

        # Gets back the basedn
        base_dn = self.ldb.domain_dn()

        # Gets back the configuration basedn
        configuration_dn = self.ldb.get_config_basedn().get_linearized()

        # Get the old "dSHeuristics" if it was set
        dsheuristics = self.ldb.get_dsheuristics()

        # Set the "dSHeuristics" to activate the correct "userPassword"
        # behaviour
        self.ldb.set_dsheuristics("000000001")

        # Reset the "dSHeuristics" as they were before
        self.addCleanup(self.ldb.set_dsheuristics, dsheuristics)

        # Get the old "minPwdAge"
        minPwdAge = self.ldb.get_minPwdAge()

        # Set it temporarily to "0"
        self.ldb.set_minPwdAge("0")
        self.base_dn = self.ldb.domain_dn()

        # Reset the "minPwdAge" as it was before
        self.addCleanup(self.ldb.set_minPwdAge, minPwdAge)

        account_control = 0
        if clear_text:
            # get the current pwdProperties
            pwdProperties = self.ldb.get_pwdProperties()
            # enable clear text properties
            props = int(pwdProperties)
            props |= DOMAIN_PASSWORD_STORE_CLEARTEXT
            self.ldb.set_pwdProperties(str(props))
            # Restore the value on exit.
            self.addCleanup(self.ldb.set_pwdProperties, pwdProperties)
            account_control |= UF_ENCRYPTED_TEXT_PASSWORD_ALLOWED

        # (Re)adds the test user USER_NAME with password USER_PASS
        # and userPrincipalName UPN
        delete_force(self.ldb, "cn=" + USER_NAME + ",cn=users," + self.base_dn)
        self.ldb.add({
             "dn": "cn=" + USER_NAME + ",cn=users," + self.base_dn,
             "objectclass": "user",
             "sAMAccountName": USER_NAME,
             "userPassword": USER_PASS,
             "userPrincipalName": UPN,
             "userAccountControl": str(account_control)
        })

    # Get the supplemental credentials for the user under test
    def get_supplemental_creds(self):
        base = "cn=" + USER_NAME + ",cn=users," + self.base_dn
        res = self.ldb.search(scope=ldb.SCOPE_BASE,
                              base=base,
                              attrs=["supplementalCredentials"])
        self.assertIs( True, len(res) > 0)
        obj = res[0]
        sc_blob = obj["supplementalCredentials"][0]
        sc = ndr_unpack(drsblobs.supplementalCredentialsBlob, sc_blob)
        return sc

    # Calculate and validate a Wdigest value
    def check_digest(self, user, realm, password,  digest):
        expected = calc_digest( user, realm, password)
        actual = binascii.hexlify(bytearray(digest))
        error = "Digest expected[%s], actual[%s], " \
                "user[%s], realm[%s], pass[%s]" % \
                (expected, actual, user, realm, password)
        self.assertEquals(expected, actual, error)

    # Check all of the 29 expected WDigest values
    #
    def check_wdigests(self, digests):

        self.assertEquals(29, digests.num_hashes)

        self.check_digest(USER_NAME,
                          self.lp.get("workgroup"),
                          USER_PASS,
                          digests.hashes[0].hash)
        self.check_digest(USER_NAME.lower(),
                          self.lp.get("workgroup").lower(),
                          USER_PASS,
                          digests.hashes[1].hash)
        self.check_digest(USER_NAME.upper(),
                          self.lp.get("workgroup").upper(),
                          USER_PASS,
                          digests.hashes[2].hash)
        self.check_digest(USER_NAME,
                          self.lp.get("workgroup").upper(),
                          USER_PASS,
                          digests.hashes[3].hash)
        self.check_digest(USER_NAME,
                          self.lp.get("workgroup").lower(),
                          USER_PASS,
                          digests.hashes[4].hash)
        self.check_digest(USER_NAME.upper(),
                          self.lp.get("workgroup").lower(),
                          USER_PASS,
                          digests.hashes[5].hash)
        self.check_digest(USER_NAME.lower(),
                          self.lp.get("workgroup").upper(),
                          USER_PASS,
                          digests.hashes[6].hash)
        self.check_digest(USER_NAME,
                          self.lp.get("realm").lower(),
                          USER_PASS,
                          digests.hashes[7].hash)
        self.check_digest(USER_NAME.lower(),
                          self.lp.get("realm").lower(),
                          USER_PASS,
                          digests.hashes[8].hash)
        self.check_digest(USER_NAME.upper(),
                          self.lp.get("realm"),
                          USER_PASS,
                          digests.hashes[9].hash)
        self.check_digest(USER_NAME,
                          self.lp.get("realm"),
                          USER_PASS,
                          digests.hashes[10].hash)
        self.check_digest(USER_NAME,
                          self.lp.get("realm").lower(),
                          USER_PASS,
                          digests.hashes[11].hash)
        self.check_digest(USER_NAME.upper(),
                          self.lp.get("realm").lower(),
                          USER_PASS,
                          digests.hashes[12].hash)
        self.check_digest(USER_NAME.lower(),
                          self.lp.get("realm"),
                          USER_PASS,
                          digests.hashes[13].hash)
        self.check_digest(UPN,
                          "",
                          USER_PASS,
                          digests.hashes[14].hash)
        self.check_digest(UPN.lower(),
                          "",
                          USER_PASS,
                          digests.hashes[15].hash)
        self.check_digest(UPN.upper(),
                          "",
                          USER_PASS,
                          digests.hashes[16].hash)

        name = "%s\\%s" % (self.lp.get("workgroup"), USER_NAME)
        self.check_digest(name,
                          "",
                          USER_PASS,
                          digests.hashes[17].hash)

        name = "%s\\%s" % (self.lp.get("workgroup").lower(), USER_NAME.lower())
        self.check_digest(name,
                          "",
                          USER_PASS,
                          digests.hashes[18].hash)

        name = "%s\\%s" % (self.lp.get("workgroup").upper(), USER_NAME.upper())
        self.check_digest(name,
                          "",
                          USER_PASS,
                          digests.hashes[19].hash)
        self.check_digest(USER_NAME,
                          "Digest",
                          USER_PASS,
                          digests.hashes[20].hash)
        self.check_digest(USER_NAME.lower(),
                          "Digest",
                          USER_PASS,
                          digests.hashes[21].hash)
        self.check_digest(USER_NAME.upper(),
                          "Digest",
                          USER_PASS,
                          digests.hashes[22].hash)
        self.check_digest(UPN,
                          "Digest",
                          USER_PASS,
                          digests.hashes[23].hash)
        self.check_digest(UPN.lower(),
                          "Digest",
                          USER_PASS,
                          digests.hashes[24].hash)
        self.check_digest(UPN.upper(),
                          "Digest",
                          USER_PASS,
                          digests.hashes[25].hash)
        name = "%s\\%s" % (self.lp.get("workgroup"), USER_NAME)
        self.check_digest(name,
                          "Digest",
                          USER_PASS,
                          digests.hashes[26].hash)

        name = "%s\\%s" % (self.lp.get("workgroup").lower(), USER_NAME.lower())
        self.check_digest(name,
                          "Digest",
                          USER_PASS,
                          digests.hashes[27].hash)

        name = "%s\\%s" % (self.lp.get("workgroup").upper(), USER_NAME.upper())
        self.check_digest(name,
                          "Digest",
                          USER_PASS,
                          digests.hashes[28].hash)
