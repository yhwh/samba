/* 
   Unix SMB/CIFS implementation.

   auth functions

   Copyright (C) Simo Sorce 2005
   Copyright (C) Andrew Tridgell 2005
   Copyright (C) Andrew Bartlett 2005
   
   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation; either version 3 of the License, or
   (at your option) any later version.
   
   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.
   
   You should have received a copy of the GNU General Public License
   along with this program.  If not, see <http://www.gnu.org/licenses/>.
*/

#include "includes.h"
#include "auth/auth.h"
#include "dsdb/samdb/samdb.h"

_PUBLIC_ NTSTATUS authenticate_ldap_simple_bind(TALLOC_CTX *mem_ctx,
						struct tevent_context *ev,
						struct imessaging_context *msg,
						struct loadparm_context *lp_ctx,
						struct tsocket_address *remote_address,
						struct tsocket_address *local_address,
						bool using_tls,
						const char *dn,
						const char *password,
						struct auth_session_info **session_info)
{
	struct auth4_context *auth_context;
	struct auth_usersupplied_info *user_info;
	struct auth_user_info_dc *user_info_dc;
	NTSTATUS nt_status;
	uint8_t authoritative = 0;
	TALLOC_CTX *tmp_ctx = talloc_new(mem_ctx);
	const char *nt4_domain = NULL;
	const char *nt4_username = NULL;
	uint32_t flags = 0;
	const char *transport_protection = AUTHZ_TRANSPORT_PROTECTION_NONE;
	if (using_tls) {
		transport_protection = AUTHZ_TRANSPORT_PROTECTION_TLS;
	}

	if (!tmp_ctx) {
		return NT_STATUS_NO_MEMORY;
	}

	nt_status = auth_context_create(tmp_ctx,
					ev, msg,
					lp_ctx,
					&auth_context);
	if (!NT_STATUS_IS_OK(nt_status)) {
		talloc_free(tmp_ctx);
		return nt_status;
	}

	/*
	 * We check the error after building the user_info so we can
	 * log a failure to find the user correctly
	 */
	nt_status = crack_auto_name_to_nt4_name(tmp_ctx, ev, lp_ctx, dn,
						&nt4_domain, &nt4_username);

	user_info = talloc_zero(tmp_ctx, struct auth_usersupplied_info);
	if (!user_info) {
		talloc_free(tmp_ctx);
		return NT_STATUS_NO_MEMORY;
	}

	user_info->client.account_name = dn;
	/* No client.domain_name, use account_name instead */
	user_info->mapped.account_name = nt4_username;
	user_info->mapped.domain_name = nt4_domain;

	user_info->workstation_name = NULL;

	user_info->remote_host = remote_address;
	user_info->local_host = local_address;

	user_info->service_description = "LDAP";

	if (using_tls) {
		user_info->auth_description = "simple bind";
	} else {
		user_info->auth_description = "simple bind/TLS";
	}

	user_info->password_state = AUTH_PASSWORD_PLAIN;
	user_info->password.plaintext = talloc_strdup(user_info, password);

	user_info->flags = USER_INFO_CASE_INSENSITIVE_USERNAME |
		USER_INFO_DONT_CHECK_UNIX_ACCOUNT;

	user_info->logon_parameters =
		MSV1_0_ALLOW_SERVER_TRUST_ACCOUNT |
		MSV1_0_ALLOW_WORKSTATION_TRUST_ACCOUNT |
		MSV1_0_CLEARTEXT_PASSWORD_ALLOWED |
		MSV1_0_CLEARTEXT_PASSWORD_SUPPLIED;

	/* This is a check for the crack names call above */
	if (!NT_STATUS_IS_OK(nt_status)) {
		log_authentication_event(auth_context->msg_ctx,
					 auth_context->lp_ctx,
					 user_info, nt_status,
					 NULL, NULL, NULL, NULL);
		talloc_free(tmp_ctx);
		return nt_status;
	}

	/* Now that we have checked if the crack names worked, set mapped_state */
	user_info->mapped_state = true;

	nt_status = auth_check_password(auth_context, tmp_ctx, user_info,
					&user_info_dc, &authoritative);
	if (!NT_STATUS_IS_OK(nt_status)) {
		talloc_free(tmp_ctx);
		return nt_status;
	}

	flags = AUTH_SESSION_INFO_DEFAULT_GROUPS;
	if (user_info_dc->info->authenticated) {
		flags |= AUTH_SESSION_INFO_AUTHENTICATED;
	}
	nt_status = auth_context->generate_session_info(auth_context,
							tmp_ctx,
							user_info_dc,
							nt4_username,
							flags,
							session_info);

	if (NT_STATUS_IS_OK(nt_status)) {
		talloc_steal(mem_ctx, *session_info);
	}

	log_successful_authz_event(auth_context->msg_ctx,
				   auth_context->lp_ctx,
				   remote_address,
				   local_address,
				   "LDAP",
				   "simple bind",
				   transport_protection,
				   *session_info);

	talloc_free(tmp_ctx);
	return nt_status;
}

