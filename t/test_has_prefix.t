package test_has_prefix;

use warnings;
use strict;

use Cwd;
use File::Temp qw/tempfile :seekable/;
use File::Spec;
use Test::More tests => 24;

my $ishlib = File::Spec->catfile(getcwd(), 'ishlib.sh');
my @shells = qw|sh bash zsh|;

sub simple {
    my $shell = shift;
    my $str = shift;
    my $prefix = shift;
    my $expected = shift;
    my $testName = shift;

    my ($fh, $fn) = tempfile();
    print $fh <<EOF;
#! /usr/bin/env $shell
. $ishlib
if has_prefix "$str" "$prefix"; then
    echo -n 0
else
    echo -n 1
fi
EOF
    close $fh;

    my $output = qx|$shell $fn / 2>&1|;
    ok($? == 0, "$shell-$testName-runs");
    ok($output eq "$expected", "$shell-$testName");

    unlink $fn;
    return;
}

my @testCases = (
    [ "12345", "123", 0 , "test01"],
    [ "12345", "321", 1 , "test02"],
    [ "====================\n", "======", 0 , "test03"],
    [ "==a=================\n", "======", 1 , "test04"],
);

for my $t (@testCases) {
    for my $shell (@shells) {
        simple($shell, $t->[0], $t->[1], $t->[2], $t->[3]);
    }
}

1;
