package test_has_prefix;

use warnings;
use strict;

use Cwd;
use File::Temp qw/tempfile :seekable/;
use File::Spec;
use Test::More tests => 48;

my $ishlib = File::Spec->catfile(getcwd(), 'ishlib.sh');
my @shells = qw|bash zsh|;

sub simple {
    my ($shell, $haystack, $needle, $e_ret, $e_pos, $testName) = @_;

    my ($fh, $fn) = tempfile();
    print $fh <<EOF;
#! /usr/bin/env $shell
set -e
. $ishlib
POS=-2
if strstr "$haystack" "$needle" POS; then
    echo -n "0-\${POS}"
else
    echo -n "1-\${POS}"
fi
EOF
    close $fh;

    my $e = "$e_ret-$e_pos";
    my $output = qx|$shell $fn / 2>&1|;

    ok($? == 0, "$shell-$testName-runs");

    $e eq $output or print STDERR "expected $e, but was $output\n";
    ok($output eq $e, "$shell-simple-$testName");

    unlink $fn;
    return;
}

sub locals_okay {
    my ($shell, $haystack, $needle, $e_ret, $e_pos, $testName) = @_;

    my ($fh, $fn) = tempfile();
    print $fh <<EOF;
#! /usr/bin/env $shell
set -e
. $ishlib
func() {
    local POS=-2
    if strstr "$haystack" "$needle" POS; then
        echo -n "0-\${POS}"
    else
        echo -n "1-\${POS}"
    fi
}
func
# Make sure POS hasn't been defined as a global
echo -n "\${POS:-}"
EOF
    close $fh;

    my $e = "$e_ret-$e_pos";
    my $output = qx|$shell $fn / 2>&1|;

    ok($? == 0, "$shell-$testName-runs");

    $e eq $output or print STDERR "expected $e, but was $output\n";
    ok($output eq $e, "$shell-locals_okay-$testName");

    unlink $fn;
    return;
}


my @testCases = (
    [ "12345", "34", 0 , 2, "test01"],
    [ "12345", "43", 1 , -1, "test02"],
    [ "0123456789\n=============\n", "abc", 1 , -1, "test03"],
    [ "012345abc9\n=============\n", "abc", 0 , 6, "test04"],
    [ "0123456789\n123456789\n=============\n", "abc", 1 , -1, "test03"],
    [ "0123456789\n123456789\nstuff========\n", "stuff", 0 , 21, "test04"],
);

for my $t (@testCases) {
    for my $shell (@shells) {
        simple($shell, $t->[0], $t->[1], $t->[2], $t->[3], $t->[4]);
        locals_okay($shell, $t->[0], $t->[1], $t->[2], $t->[3], $t->[4]);
    }
}

1;