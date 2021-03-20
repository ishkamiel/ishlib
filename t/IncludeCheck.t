package Includecheck;

use warnings;
use strict;

use Cwd;
use File::Temp qw/tempfile :seekable/;
use File::Spec;
use Test::More tests => 24;

my @shells = qw|sh bash zsh|;

my $ishlib = File::Spec->catfile(getcwd(), 'ishlib.sh');

sub source_test_silent {
    my $shell = shift;

    my ($fh, $fn) = tempfile();
    print $fh <<EOF;
#! /usr/bin/env $shell

. $ishlib
EOF
    close $fh;

    my $output = qx|$shell $fn / 2>&1|;
    ok($? == 0, "$shell-source_test_silent-runs");
    ok($output eq "", "$shell-source_test_silent");
    return;
}

sub source_test_with_debug {
    my $shell = shift;

    my ($fh, $fn) = tempfile();
    print $fh <<EOF;
#! /usr/bin/env $shell

DEBUG=1

. $ishlib
EOF
    close $fh;

    my $output = qx|$shell $fn / 2>&1|;
    ok($? == 0, "$shell-source_test_with_debug-runs");
    ok($output =~ m/^[^\w]*[DD]/, "$shell-source_test_with_debug");
    return;
}

sub direct_run {
    my $shell = shift;

    my $output = qx|$shell $ishlib / 2>&1|;
    ok($? == 0, "$shell-direct_run-runs | head");
    ok($output =~ m/^\[WW\]/, "$shell-direct_run");
    return;
}

sub direct_run_help {
    my $shell = shift;

    my $output = qx|$shell $ishlib -h / 2>&1|;
    ok($? == 0, "$shell-direct_run_help-runs | head");
    ok($output =~ m/^ishlib/, "$shell-direct_run_help");
    return;
}

for my $shell (@shells) {
    my ($fh, $fn, $output);
    source_test_silent($shell);
    source_test_with_debug($shell);
    direct_run($shell);
    direct_run_help($shell);
}

1;