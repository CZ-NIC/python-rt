# RT initial data for the tests which need more than a fresh RT, for the image ghcr.io/python-rt/request-tracker
# (https://github.com/python-rt/docker-rt): a custom field and a custom role of the queue General (REST2 can not
# create custom roles).
#
# Locally, mounted into the init directory of the container, it is inserted on the first start:
#
#   docker run --rm --name rt -p 8080:8080 \
#     -v ./tests/rt_initdata.pl:/docker-entrypoint-init.d/python-rt.pl:ro ghcr.io/python-rt/request-tracker:6.0
#
# REST2 can not create authentication tokens either, the tests needing this or the custom field are skipped unless
# RT_TOKEN is set:
#
#   export RT_TOKEN=$(docker exec rt rt-token)
#
# In a running container it can also be inserted with (once, it is not checked whether the data exists):
#
#   docker exec -i rt rt-initdata - < tests/rt_initdata.pl

# must match RT_CUSTOM_FIELD in tests/conftest.py, the quote and the space test the quoting
@CustomFields = (
    {
        Name       => "python-rt Test's Field",
        Type       => 'FreeformSingle',
        LookupType => 'RT::Queue-RT::Ticket',
        Queue      => ['General'],
    },
);

# must match RT_CUSTOM_ROLE in tests/conftest.py; REST2 can not create custom roles
@CustomRoles = (
    {
        Name      => 'python-rt Test Role',
        MaxValues => 1,
        ApplyTo   => 'General',
    },
);

1;
