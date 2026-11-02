# Prepare the RT test container for the tests which need more than a fresh RT.
#
# REST2 can neither create authentication tokens nor apply custom fields to a queue, so this script uses
# the Perl API of RT inside the container:
#
#   - creates the ticket custom field "python-rt Test's Field" (if missing) and applies it to the queue General
#   - creates an authentication token for the user root and prints it (only the token is printed to stdout)
#
# Usage (the tests needing it are skipped unless RT_TOKEN is set):
#
#   export RT_TOKEN=$(docker exec -i rt perl - < tests/rt_setup.pl)
#
# The script can be run more than once; every run creates a new token.

use strict;
use warnings;

use lib '/opt/rt/lib', '/opt/rt/local/lib';

use RT;
RT::LoadConfig();
RT::Init();

# must match RT_CUSTOM_FIELD in tests/conftest.py
my $cf_name = "python-rt Test's Field";

my $queue = RT::Queue->new(RT->SystemUser);
$queue->Load('General');
die "Queue General not found\n" unless $queue->Id;

my $cf = RT::CustomField->new(RT->SystemUser);
$cf->LoadByName(Name => $cf_name, LookupType => RT::Ticket->CustomFieldLookupType);
unless ($cf->Id) {
    my ($ok, $msg) = $cf->Create(
        Name       => $cf_name,
        Type       => 'FreeformSingle',
        LookupType => RT::Ticket->CustomFieldLookupType,
    );
    die "Creating the custom field failed: $msg\n" unless $ok;
}

unless ($cf->IsAdded($queue->Id)) {
    my ($ok, $msg) = $cf->AddToObject($queue);
    die "Applying the custom field to the queue failed: $msg\n" unless $ok;
}

my $user = RT::User->new(RT->SystemUser);
$user->Load('root');
die "User root not found\n" unless $user->Id;

my ($id, $msg, $token) = RT::AuthToken->new(RT::CurrentUser->new($user))->Create(
    Owner       => $user->Id,
    Description => 'python-rt tests',
);
die "Creating the authentication token failed: $msg\n" unless $id;

print "$token\n";
